package golf.sportfix;
import golf.sportconfig.GaugeOptions;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import de.vw.mib.asl.framework.api.dsiproxy.DSIProxyFactory;
import de.vw.mib.hmi.internal.ServiceManagerCommon;
import de.vw.mib.viewmanager.internal.ViewHandler;

/** Three distinct trials: preflight, same-value write check, or enabled binding. */
public final class SportsBootstrap {
    private static boolean queued;
    private SportsBootstrap() { }
    public static synchronized void install() {
        if (queued) return;
        queued = true;
        try {
            if (ServiceManagerCommon.hmiThreadInvoker == null) throw new IllegalStateException("no-hmi-invoker");
            ServiceManagerCommon.hmiThreadInvoker.invoke(new Runnable() { public void run() { installOnHmi(); } });
        } catch (Throwable error) { status("failed:queue:" + error.getClass().getName()); }
    }
    private static String mode() throws Exception { return GaugeOptions.mode(); }
    private static void installOnHmi() {
        CarFactoryBinding factory = null; PersistenceBinding persistence = null; SportSource source = null; SourceProfile profile = null;
        String stage = "mode";
        try {
            String selected = mode();
            if ("disabled".equals(selected) || !GaugeOptions.needsSports()) { status("disabled:config"); return; }
            stage = "ui-linkage";
            SportPluginLoader plugin = new SportPluginLoader("/persistence/golf-sports-configurator/sport-ui.jar", SportsBootstrap.class.getClassLoader());
            if (!ViewHandler.class.isAssignableFrom(plugin.loadClass("golf.sporttrial.CsdTorque"))) throw new IllegalStateException("wrong-view-interface");
            stage = "car-app-lookup";
            factory = new CarFactoryBinding(CarAppLookup.find(), plugin);
            stage = "persistence-preflight";
            persistence = new PersistenceBinding();
            stage = "sport-cache-check";
            boolean cached = CarAppLookup.sportCached();
            if ("preflight".equals(selected)) { status("ready:preflight:mutable-car-factory:sport-cached=" + cached); return; }
            if ("self-write".equals(selected)) {
                stage = "same-value-persistence-write"; status("stage:" + stage); persistence.checkWrite();
                stage = "same-value-car-factory-write"; status("stage:" + stage); factory.checkWrite();
                status("ready:self-write:both-slots-verified:sport-cached=" + cached); return;
            }
            if (cached) throw new IllegalStateException("requires-unloaded-sport-view");
            stage = "source-construction";
            source = new SportSource(DSIProxyFactory.getDSIProxyAPI().getDSIProxy());
            stage = "source-profile";
            profile = new SourceProfile(); profile.apply();
            stage = "source-register"; status("stage:" + stage); source.register();
            stage = "persistence-bind"; status("stage:" + stage); persistence.apply();
            stage = "car-factory-bind"; status("stage:" + stage); factory.apply();
            status("registered:car-factory:configured");
        } catch (Throwable error) {
            boolean cleanup = true;
            try { if (factory != null) factory.restore(); } catch (Throwable ignored) { cleanup = false; }
            try { if (persistence != null) persistence.restore(); } catch (Throwable ignored) { cleanup = false; }
            try { if (source != null) source.remove(); } catch (Throwable ignored) { cleanup = false; }
            try { if (profile != null) profile.restore(); } catch (Throwable ignored) { cleanup = false; }
            status("failed:" + stage + ":" + error.getClass().getName() + ":" + error.getMessage() + ":cleanup=" + cleanup);
        }
    }
    public static void status(String value) {
        try {
            FileOutputStream output = new FileOutputStream("/tmp/golf-power-torque-v7.status");
            try { output.write(("sport-v7 " + System.currentTimeMillis() + " " + value + "\n").getBytes("US-ASCII")); }
            finally { output.close(); }
        } catch (Throwable ignored) { }
    }
}
