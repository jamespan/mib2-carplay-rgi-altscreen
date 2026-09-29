import de.audi.app.terminalmode.dsi.IDSIResource;
import de.audi.app.terminalmode.dsi.carplay.CarplayDSILifecycleController;
import de.audi.app.terminalmode.dsi.carplay.CarplayUtils;
import de.audi.app.terminalmode.dsi.carplay.IDSICarplayTransferObjectFactory;
import de.audi.atip.log.NullLogChannel;
import java.lang.reflect.*;
import java.util.Arrays;
import org.dsi.ifc.carplay.ResourceRequest;
import sun.misc.Unsafe;

/** Exercise the built CN resource path for initial/reconnect and both owners.
 * Framework construction is skipped; the actual private converter is executed.
 * The expected priority (initial=2, update=1) is from original CN ROM bytecode.
 */
public final class CnResourceRequestTest {
    static void set(Object object, String name, Object value) throws Exception {
        for (Class<?> c=object.getClass(); c!=null; c=c.getSuperclass()) {
            try {
                Field f=c.getDeclaredField(name); f.setAccessible(true); f.set(object,value); return;
            } catch (NoSuchFieldException ignored) { }
        }
        throw new NoSuchFieldException(name);
    }
    public static void main(String[] args) throws Exception {
        Field uf=Unsafe.class.getDeclaredField("theUnsafe"); uf.setAccessible(true);
        Unsafe unsafe=(Unsafe)uf.get(null);
        Object outer=unsafe.allocateInstance(CarplayDSILifecycleController.class);
        set(outer,"logger",NullLogChannel.getInstance());
        final int[][] observed=new int[1][];
        Object factory=Proxy.newProxyInstance(CnResourceRequestTest.class.getClassLoader(),
            new Class[]{IDSICarplayTransferObjectFactory.class},new InvocationHandler() {
                public Object invoke(Object p,Method m,Object[] a) {
                    if (!m.getName().equals("createResourceRequest")) throw new AssertionError(m);
                    observed[0]=new int[a.length];
                    for(int i=0;i<a.length;i++) observed[0][i]=((Integer)a[i]).intValue();
                    return new ResourceRequest();
                }
            });
        set(outer,"transferObjectFactory",factory);
        Class<?> innerClass=Class.forName(CarplayDSILifecycleController.class.getName()+"$CarplayDSIController");
        Object inner=unsafe.allocateInstance(innerClass);
        set(inner,"this$0",outer);
        Method convert=innerClass.getDeclaredMethod("convertResource2DSIResourceRequest",IDSIResource[].class,Boolean.TYPE);
        convert.setAccessible(true);
        int checks=0;
        for(final int owner:new int[]{0,1}) for(boolean initial:new boolean[]{false,true}) {
            IDSIResource resource=(IDSIResource)Proxy.newProxyInstance(CnResourceRequestTest.class.getClassLoader(),
                new Class[]{IDSIResource.class},new InvocationHandler() {
                    public Object invoke(Object p,Method m,Object[] a) {
                        if (a!=null && a.length!=0) throw new AssertionError("CN getters take no boolean: "+m);
                        String n=m.getName();
                        if(n.equals("getDSIResourceId")||n.equals("getResourceId")) return Integer.valueOf(7);
                        if(n.equals("getOwner")) return Integer.valueOf(owner);
                        if(n.equals("getDSITakeType")) return Integer.valueOf(2);
                        if(n.equals("getDSITakeConstraint")) return Integer.valueOf(11);
                        if(n.equals("getDSIBorrowConstraint")) return Integer.valueOf(12);
                        if(n.equals("getDSIUnborrowConstraint")) return Integer.valueOf(13);
                        throw new AssertionError("Unexpected CN getter: "+m);
                    }
                });
            ResourceRequest[] result=(ResourceRequest[])convert.invoke(inner,new Object[]{new IDSIResource[]{resource},Boolean.valueOf(initial)});
            int[] expected={7,owner==1?2:CarplayUtils.getInvertTransferType(2),initial?2:1,11,12,13};
            if(result.length!=1||!Arrays.equals(expected,observed[0])) throw new AssertionError(Arrays.toString(observed[0]));
            checks++;
        }
        ResourceRequest[] empty=(ResourceRequest[])convert.invoke(inner,new Object[]{new IDSIResource[0],Boolean.FALSE});
        if(empty.length!=0) throw new AssertionError("empty resources");
        System.out.println("CnResourceRequestTest: "+checks+" initial/update and owner combinations + empty PASS");
    }
}
