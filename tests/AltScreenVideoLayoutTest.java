import com.luka.carplay.cluster.AltScreenVideoLayout;
import com.luka.carplay.framework.Log;
import de.audi.atip.hmi.view.IDisplayManager;
import de.esolutions.hmi.widgets.audi.base.Layout;
import de.esolutions.hmi.widgets.audi.evo.high.LayoutMIB2HighB9;
import de.esolutions.hmi.widgets.audi.evo.high.LayoutMIB2HighB9Sport;
import java.io.*;
import java.lang.reflect.*;

/** Real CN OEM layout, current-process phase records, and a recording DSI boundary. */
public final class AltScreenVideoLayoutTest implements InvocationHandler {
    int x, y, writes;
    boolean fail;
    static File dir;
    static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static void put(String name, String value) throws Exception {
        FileOutputStream out = new FileOutputStream(new File(dir, name));
        out.write(value.getBytes("ISO-8859-1")); out.close();
    }
    static String read(String name) throws Exception {
        BufferedReader in = new BufferedReader(new FileReader(new File(dir,name)));
        String value=in.readLine(); in.close(); return value;
    }
    public Object invoke(Object proxy, Method method, Object[] args) {
        if (method.getName().equals("setPosition")) {
            check(((Integer)args[0]).intValue()==3 && ((Integer)args[1]).intValue()==1,
                "must touch only AltScreen video, never native map / maneuver planes");
            if (fail) throw new RuntimeException("DSI unavailable");
            x=((Integer)args[2]).intValue();y=((Integer)args[3]).intValue();writes++;
        }
        Class type=method.getReturnType();
        if(type==Boolean.TYPE)return Boolean.FALSE;
        if(type==Integer.TYPE)return Integer.valueOf(0);
        return null;
    }
    void at(int expected, String message) { check(x==expected&&y==0,message+": "+x+","+y); }
    static String phase(String pid, String mode) {
        return "ready=1\npid="+pid+"\nmode="+mode+"\ndisplayable=3\nwindow58_readback=0\n";
    }
    public static void main(String[] args) throws Exception {
        Log.setLevel(-1);
        dir=new File(System.getProperty("java.io.tmpdir"),"alt-video-layout-"+System.nanoTime());
        check(dir.mkdirs(),"scratch directory");
        Field root=AltScreenVideoLayout.class.getDeclaredField("tmpRoot");root.setAccessible(true);root.set(null,dir.getPath());
        AltScreenVideoLayoutTest capture=new AltScreenVideoLayoutTest();
        IDisplayManager dm=(IDisplayManager)Proxy.newProxyInstance(AltScreenVideoLayoutTest.class.getClassLoader(),new Class[]{IDisplayManager.class},capture);
        Layout sport=new LayoutMIB2HighB9Sport(), classic=new LayoutMIB2HighB9();
        check(sport.getIntegerConstant(80)==-476&&sport.getIntegerConstant(81)==0,"actual CN Sport OEM offset");
        AltScreenVideoLayout.updateLayout(sport,true);
        AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"no stream stays centered");
        check(!new File(dir,"carplay-video-position.used").exists(),"origin-only sessions need no next-launch handshake");
        put("mmi-mirror-active","");put("MMI-Cockpit-Carplay.mirror.pid","41\n");
        put("mmi-mirror-basevideo.ready",phase("41","startup-logo"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"logo never shifts even in Sport SMALL");
        put("mmi-mirror-basevideo.ready",phase("41","direct-display"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(-476,"real video follows OEM small-map offset");
        check(new File(dir,"carplay-video-position.used").isFile(),"nonzero position publishes next-launch reset obligation");
        int writes=capture.writes;
        for(int i=0;i<20;i++)AltScreenVideoLayout.reconcile(dm,true);
        check(capture.writes==writes,"stable video has no repeated DSI writes");
        AltScreenVideoLayout.updateLayout(sport,false);AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"full map resets");
        AltScreenVideoLayout.updateLayout(sport,true);AltScreenVideoLayout.reconcile(dm,true);capture.at(-476,"small map returns");
        AltScreenVideoLayout.updateLayout(classic,true);AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"Classic must not inherit Sport translation");
        AltScreenVideoLayout.updateLayout(sport,true);
        put("mmi-mirror-basevideo.ready",phase("40","direct-display"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"stale ready PID rejected");
        put("mmi-mirror-basevideo.ready",phase("41","direct-display").trim());
        AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"partially published marker rejected");
        put("mmi-mirror-basevideo.ready",phase("41","sink-test-grid"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"diagnostic grid is not video");
        put("mmi-mirror-basevideo.ready",phase("41","direct-display"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(-476,"valid video recovered");
        AltScreenVideoLayout.reconcile(dm,false);capture.at(0,"disconnect restores video plane");
        AltScreenVideoLayout.reconcile(dm,true);capture.at(-476,"video active again");
        new File(dir,"mmi-mirror-basevideo.ready").delete();
        put("carplay-video-reset.request","launcher:1\n");capture.fail=true;
        AltScreenVideoLayout.reconcile(dm,false);
        check(!new File(dir,"carplay-video-reset.ack").exists(),"failed DSI reset must not ack/start logo");
        capture.fail=false;AltScreenVideoLayout.reconcile(dm,false);capture.at(0,"reset works while disconnected");
        check("launcher:1".equals(read("carplay-video-reset.ack")),"ack only after successful origin write");
        put("MMI-Cockpit-Carplay.mirror.pid","42\n");put("mmi-mirror-basevideo.ready",phase("42","startup-logo"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"reconnected project's logo remains centered");
        put("mmi-mirror-basevideo.ready",phase("42","direct-display"));
        AltScreenVideoLayout.reconcile(dm,true);capture.at(-476,"new process video shifts");
        new File(dir,"mmi-mirror-active").delete();AltScreenVideoLayout.reconcile(dm,true);capture.at(0,"demand loss restores origin");
        File[] files=dir.listFiles();for(int i=0;i<files.length;i++)files[i].delete();dir.delete();
        System.out.println("AltScreenVideoLayoutTest: real CN Sport -476, logo/map, stale/partial phases, Classic/FULL, reconnect reset/failure and single-plane writes PASS");
    }
}
