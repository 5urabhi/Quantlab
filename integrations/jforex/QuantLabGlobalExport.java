// Run LOCAL in JForex only with authorized data access/storage.
// No engine, account credentials, orders, position changes, HTTP or scraping.
import com.dukascopy.api.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;

public class QuantLabGlobalExport implements IStrategy {
    private static final String[] SYMBOLS = {
        "JPN.IDX/JPY","SGD.IDX/SGD","CHI.IDX/USD","HKG.IDX/HKD","AUS.IDX/AUD",
        "USA500.IDX/USD","USATECH.IDX/USD","DEU.IDX/EUR","GBR.IDX/GBP","EUS.IDX/EUR"
    };
    private static final String HEADER =
        "instrument,interval_minutes,side,bar_start_ms,open,high,low,close,volume,exported_ms";
    @Configurable("Authorized research export and local storage reviewed")
    public boolean approved = false;
    @Configurable("History from UTC (blank = last 7 days)")
    public String fromDate = "";
    @Configurable("History to UTC exclusive (blank = today)")
    public String toDate = "";
    @Configurable("Resolution minutes (1 or 5)")
    public int minutes = 5;
    @Configurable("Live only (no historical backfill)")
    public boolean live = false;
    @Configurable("Replace existing historical export for explicit repair")
    public boolean repair = false;
    @Configurable("Single exact instrument (blank = all)")
    public String onlyInstrument = "";
    private IContext context;
    private File folder;
    private Period period;
    private final Map<Instrument,String> instruments = new LinkedHashMap<>();

    private long utc(LocalDate d) { return d.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(); }
    private String fileKey(String symbol) { return symbol.replaceAll("[^A-Za-z0-9]", "_"); }

    public void onStart(IContext c) throws JFException {
        context=c;
        if (!approved || (minutes!=1 && minutes!=5)) {
            c.getConsole().getErr().println("Review permitted data use and choose 1 or 5 minutes.");
            c.stop(); return;
        }
        period=minutes==1?Period.ONE_MIN:Period.FIVE_MINS;
        for (String symbol: SYMBOLS) {
            if (!onlyInstrument.isEmpty() && !symbol.equals(onlyInstrument)) continue;
            Instrument instrument=Instrument.fromString(symbol);
            if (instrument==null || !symbol.equals(instrument.toString())) {
                c.getConsole().getErr().println("Instrument unavailable: "+symbol); continue;
            }
            instruments.put(instrument,symbol);
        }
        if (instruments.isEmpty()) { c.getConsole().getErr().println("No exact supported instruments."); c.stop(); return; }
        c.setSubscribedInstruments(new HashSet<>(instruments.keySet()),true);
        folder=new File(c.getFilesDir(),live?"quantlab_global_live":"quantlab_global_archive");
        if ((!folder.exists() && !folder.mkdirs()) || !folder.isDirectory()) {
            c.getConsole().getErr().println("Cannot create export folder."); c.stop(); return;
        }
        c.getConsole().getOut().println("QuantLab export directory: "+folder.getAbsolutePath());
        if (live) return;
        try {
            LocalDate today=LocalDate.now(ZoneOffset.UTC);
            LocalDate stop=toDate.trim().isEmpty()?today:LocalDate.parse(toDate);
            LocalDate start=fromDate.trim().isEmpty()?stop.minusDays(7):LocalDate.parse(fromDate);
            if (!start.isBefore(stop) || stop.isAfter(today) || start.isBefore(stop.minusYears(5).minusDays(2)))
                throw new IllegalArgumentException("Use a past, bounded period up to five years.");
            for (Map.Entry<Instrument,String> entry:instruments.entrySet()) {
                for (LocalDate day=start; day.isBefore(stop) && !c.isStopped();) {
                    LocalDate next=day.withDayOfMonth(1).plusMonths(1);
                    if (next.isAfter(stop)) next=stop;
                    String name=fileKey(entry.getValue())+"_"+minutes+"m_"+day+"_"+next+".csv";
                    File target=new File(folder,name);
                    if (repair || !target.isFile() || target.length()<=HEADER.length()+2) {
                        try {
                            List<IBar> bars=c.getHistory().getBars(entry.getKey(),period,OfferSide.BID,
                                Filter.WEEKENDS,utc(day),utc(next)-minutes*60000L);
                            int count=write(target,entry.getValue(),bars,utc(day),utc(next));
                            c.getConsole().getOut().println(name+" rows="+count+" (not coverage certification)");
                        } catch (JFException | IOException | RuntimeException e) {
                            c.getConsole().getErr().println(name+" unavailable: "+e.getClass().getSimpleName());
                        }
                        Thread.sleep(1000L);
                    }
                    day=next;
                }
                if (c.isStopped()) break;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (RuntimeException e) {
            c.getConsole().getErr().println("Export configuration failed: "+e.getMessage());
        } finally { c.stop(); }
    }

    private int write(File target,String symbol,List<IBar> bars,long start,long stop) throws IOException {
        if (bars==null || bars.isEmpty()) return 0; // no false completed file
        long exported=System.currentTimeMillis(), step=minutes*60000L;
        Path temp=Files.createTempFile(folder.toPath(),"quantlab_",".tmp");
        int count=0;
        try {
            try (BufferedWriter out=Files.newBufferedWriter(temp,StandardCharsets.UTF_8)) {
                out.write(HEADER); out.newLine();
                for (IBar b:bars) {
                    long t=b.getTime();
                    if (t<start || t>=stop || t%step!=0 || t+step>exported) continue;
                    out.write(symbol+","+minutes+",BID,"+t+","+b.getOpen()+","+b.getHigh()+","+
                        b.getLow()+","+b.getClose()+","+b.getVolume()+","+exported);
                    out.newLine(); count++;
                }
            }
            if (count>0) Files.move(temp,target.toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
        } finally { Files.deleteIfExists(temp); }
        return count;
    }

    public void onBar(Instrument i,Period p,IBar ask,IBar bid) throws JFException {
        if (!live || p!=period || !instruments.containsKey(i) || bid==null) return;
        long t=bid.getTime();
        File target=new File(folder,fileKey(instruments.get(i))+"_"+minutes+"m_"+t+".csv");
        if (target.isFile()) return;
        try { write(target,instruments.get(i),Collections.singletonList(bid),t,t+minutes*60000L); }
        catch (IOException | RuntimeException e) {
            context.getConsole().getErr().println("Live export failed: "+e.getClass().getSimpleName());
        }
    }
    public void onAccount(IAccount account) throws JFException {}
    public void onMessage(IMessage message) throws JFException {}
    public void onStop() throws JFException {}
    public void onTick(Instrument i,ITick tick) throws JFException {}
}
