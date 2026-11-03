package golf.temperaturefix;

import golf.sportconfig.GaugeOptions;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.WeakHashMap;

import de.vw.mib.asl.framework.api.dsiproxy.DSIProxy;
import de.vw.mib.asl.framework.api.dsiproxy.DSIProxyFactory;
import de.vw.mib.asl.framework.api.dsiproxy.DSIProxyInterceptor;
import de.vw.mib.asl.framework.internal.framework.dsi.util.Utils;
import org.dsi.ifc.carkombi.DSICarKombiListener;
import org.dsi.ifc.global.CarBCTemperature;

/** Exact CXSA/MU0757 profile: copy two raw DSI temperatures before stock dispatch. */
public final class TemperatureBridge implements DSIProxyInterceptor {
    private static final String MARKER = "/persistence/golf-temperature-fix/oil-coolant-x10.enabled";
    private static final String TOKEN = "oil+coolant-x10-cxsa-mu0757-v1\n";
    private static final String LISTENER = "org.dsi.ifc.carkombi.DSICarKombiListener";
    private static final String STATUS = "golf.temperaturefix.status";
    private static final String STATUS_FILE = "/tmp/golf-temperaturefix.status";
    private static TemperatureBridge installed;
    private static DSIProxy registeredProxy;

    private final int typeIndex;
    private final WeakHashMap correctedCopies = new WeakHashMap();
    private volatile boolean active;

    private TemperatureBridge(int index) {
        typeIndex = index;
    }

    /** Called only by the protected existing TestInterface factory constructor. */
    public static synchronized void install() {
        try {
            if (installed != null) {
                status(installed.active ? GaugeOptions.temperatureStatus() : "failed:inactive-registration");
                return;
            }
            if (!GaugeOptions.temperaturesActive()) {
                status("disabled:config");
                return;
            }
            installOn(DSIProxyFactory.getDSIProxyAPI().getDSIProxy());
        } catch (Throwable problem) {
            status("failed:install:" + problem.getClass().getName());
        }
    }

    private static boolean markerEnabled(String path) throws IOException {
        File marker = new File(path);
        if (!marker.isFile()) return false;
        FileInputStream stream = new FileInputStream(marker);
        try {
            for (int index = 0; index < TOKEN.length(); index++) {
                if (stream.read() != (int) TOKEN.charAt(index)) return false;
            }
            return stream.read() == -1;
        } finally {
            stream.close();
        }
    }

    /** Kept private; desktop tests may inspect this boundary without unit paths. */
    private static synchronized void installOn(DSIProxy proxy) {
        if (installed != null) {
            status(installed.active ? GaugeOptions.temperatureStatus() : "failed:inactive-registration");
            return;
        }
        if (proxy == null) {
            status("failed:no-proxy");
            return;
        }
        TemperatureBridge candidate = null;
        try {
            int index = Utils.getTypeIndex(DSICarKombiListener.class);
            if (index < 0) {
                status("failed:listener-type");
                return;
            }
            candidate = new TemperatureBridge(index);
            proxy.addListenerInterceptor(DSICarKombiListener.class, 0, candidate);
            installed = candidate;
            registeredProxy = proxy;
            candidate.active = true;
            status(GaugeOptions.temperatureStatus());
        } catch (Throwable problem) {
            if (candidate != null) {
                candidate.active = false;
                try {
                    proxy.removeListenerInterceptor(DSICarKombiListener.class, 0, candidate);
                } catch (Throwable cleanupProblem) {
                    // Retain a disabled reference so uninstall can retry removal.
                    installed = candidate;
                    registeredProxy = proxy;
                }
            }
            status("failed:register:" + problem.getClass().getName());
        }
    }

    /** Disables correction first; an in-flight stock event may already be queued. */
    public static synchronized void uninstall() {
        if (installed == null) {
            status("disabled:uninstalled");
            return;
        }
        installed.active = false;
        try {
            registeredProxy.removeListenerInterceptor(DSICarKombiListener.class, 0, installed);
            installed = null;
            registeredProxy = null;
            status("disabled:uninstalled");
        } catch (Throwable problem) {
            status("disabled:remove-failed:" + problem.getClass().getName());
        }
    }

    public synchronized boolean before(String listener, int instance, int method, Object[] args) {
        try {
            if (!active || instance != 0 || !LISTENER.equals(listener)) return true;
            String name = Utils.getRuntimeListenerMethodName(typeIndex, method);
            if (!"updateBCOilTemperatureValue".equals(name)
                && !"updateBCCoolantTemperature".equals(name)) return true;
            if ("updateBCOilTemperatureValue".equals(name) && !GaugeOptions.oil()) return true;
            if ("updateBCCoolantTemperature".equals(name) && !GaugeOptions.coolant()) return true;
            if (args == null || args.length != 2 || !(args[1] instanceof Integer)
                || ((Integer) args[1]).intValue() != 1 || args[0] == null
                || args[0].getClass() != CarBCTemperature.class) return true;
            CarBCTemperature source = (CarBCTemperature) args[0];
            if (source.state != 1 || source.temperatureUnit != 0
                || correctedCopies.containsKey(source)) return true;
            float raw = source.temperatureValue;
            if (Float.isNaN(raw) || Float.isInfinite(raw)) return true;
            float corrected = raw * 10.0f;
            if (Float.isNaN(corrected) || Float.isInfinite(corrected)) return true;
            CarBCTemperature copy = new CarBCTemperature(source.state, corrected, source.temperatureUnit);
            // This DTO does not override equals/hashCode: weak keys track identity.
            correctedCopies.put(copy, Boolean.TRUE);
            args[0] = copy;
        } catch (Throwable problem) {
            // Preserve native delivery. Assignment occurs only after all guards/copy.
        }
        return true;
    }

    public void after(String listener, int instance, int method, Object[] args) {
        // Native queue, caches, original handlers and all subscriptions remain owned by OEM code.
    }

    private static void status(String value) {
        try {
            System.setProperty(STATUS, value);
        } catch (Throwable ignored) {
            // Status visibility cannot affect startup or delivery.
        }
        try {
            String line = "temperature-hook-v3 " + System.currentTimeMillis() + " " + value + "\n";
            FileOutputStream stream = new FileOutputStream(STATUS_FILE);
            try {
                stream.write(line.getBytes("US-ASCII"));
            } finally {
                stream.close();
            }
        } catch (Throwable ignored) {
            // /tmp is /dev/shmem on this firmware; diagnostics remain optional.
        }
    }
}
