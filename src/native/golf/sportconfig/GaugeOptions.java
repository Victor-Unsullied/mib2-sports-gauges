package golf.sportconfig;

import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.ByteArrayInputStream;
import java.util.Properties;

/** Strict per-boot configuration. No file, invalid data or disabled phase means no fixes. */
public final class GaugeOptions {
    private static Properties options = new Properties();
    private static String phase = "disabled";
    private static String profile = "invalid";
    private static boolean valid;
    private static final String[] GAUGE_KEYS = {"gauge_boost","gauge_gmeter","gauge_coolant","gauge_power","gauge_oil"};
    static {
        try {
            FileInputStream input = new FileInputStream("/persistence/golf-sports-configurator/options.properties");
            byte[] data = new byte[2049]; int count = 0, next;
            try { while ((next = input.read()) != -1 && count < data.length) data[count++] = (byte)next; }
            finally { input.close(); }
            if (count > 2048) throw new IllegalArgumentException("oversized-options");
            Properties candidate = new Properties();
            candidate.load(new ByteArrayInputStream(data, 0, count));
            if (candidate.size() != 18 || !"4".equals(candidate.getProperty("version"))) throw new IllegalArgumentException("schema");
            check(candidate, "oil", new String[]{"true","false"});
            check(candidate, "coolant", new String[]{"true","false"});
            check(candidate, "torque", new String[]{"true","false"});
            check(candidate, "gauge_boost", new String[]{"true","false"});
            check(candidate, "gauge_gmeter", new String[]{"true","false"});
            check(candidate, "gauge_coolant", new String[]{"true","false"});
            check(candidate, "gauge_power", new String[]{"true","false"});
            check(candidate, "gauge_oil", new String[]{"true","false"});
            check(candidate, "power_source", new String[]{"factory","torque"});
            check(candidate, "smoothing", new String[]{"none","stock500"});
            check(candidate, "power_unit", new String[]{"factory","hp","kw"});
            checkRange(candidate, "torque");
            checkRange(candidate, "power");
            check(candidate, "mode", new String[]{"disabled","preflight","self-write","enabled"});
            String id = candidate.getProperty("profile_id");
            if (id == null || id.length() != 16) throw new IllegalArgumentException("profile-id");
            for (int i=0;i<id.length();i++) if ("0123456789abcdef".indexOf(id.charAt(i)) < 0) throw new IllegalArgumentException("profile-id");
            options = candidate; phase = options.getProperty("mode"); profile = id; valid = true;
        } catch (Throwable ignored) { valid = false; phase = "disabled"; }
        try {
            FileOutputStream out = new FileOutputStream("/tmp/golf-sportconfig.status");
            try { out.write(("sportconfig-v4 " + System.currentTimeMillis() + " " + (valid ? phase : "invalid") + ":" + profile + "\n").getBytes("US-ASCII")); }
            finally { out.close(); }
        } catch (Throwable ignored) { }
    }
    private GaugeOptions() { }
    private static void checkRange(Properties p, String kind) {
        String lower = p.getProperty(kind + "_min"), upper = p.getProperty(kind + "_max");
        if ("auto".equals(lower) && "auto".equals(upper)) return;
        int min = Integer.parseInt(lower), max = Integer.parseInt(upper);
        if (!String.valueOf(min).equals(lower) || !String.valueOf(max).equals(upper)
            || min < 0 || min >= max || max > 999) throw new IllegalArgumentException(kind + "-range");
    }
    public static boolean customRange(String kind) {
        return valid && options.getProperty(kind + "_min") != null && !"auto".equals(options.getProperty(kind + "_min"));
    }
    public static int lowerLimit(String kind, int fallback) {
        return customRange(kind) ? Integer.parseInt(options.getProperty(kind + "_min")) : fallback;
    }
    public static int upperLimit(String kind, int fallback) {
        return customRange(kind) ? Integer.parseInt(options.getProperty(kind + "_max")) : fallback;
    }
    private static void check(Properties p, String key, String[] allowed) {
        String value = p.getProperty(key);
        for (int i=0;i<allowed.length;i++) if (allowed[i].equals(value)) return;
        throw new IllegalArgumentException(key);
    }
    public static String mode() { return phase; }
    public static boolean active() { return valid && "enabled".equals(phase); }
    public static boolean oil() { return active() && "true".equals(options.getProperty("oil")); }
    public static boolean coolant() { return active() && "true".equals(options.getProperty("coolant")); }
    public static boolean temperaturesActive() { return oil() || coolant(); }
    public static String temperatureStatus() { return oil() && coolant() ? "registered:oil+coolant-x10" : oil() ? "registered:oil-x10" : "registered:coolant-x10"; }
    public static boolean torque() { return valid && "true".equals(options.getProperty("torque")); }
    public static boolean derivedPower() { return valid && "torque".equals(options.getProperty("power_source")); }
    public static boolean smoothing() { return valid && "stock500".equals(options.getProperty("smoothing")); }
    public static boolean factoryUnit() { return !valid || "factory".equals(options.getProperty("power_unit")); }
    public static int powerUnit(int factory) { return !valid || factoryUnit() ? factory : "hp".equals(options.getProperty("power_unit")) ? 2 : 0; }
    public static boolean gauge(int index) {
        if (index == 5) return torque();
        return !valid || !"false".equals(options.getProperty(GAUGE_KEYS[index]));
    }
    public static boolean anyGauge() { for (int i=0;i<6;i++) if (gauge(i)) return true; return false; }
    public static boolean needsSports() {
        if (!valid) return false;
        for (int i=0;i<5;i++) if (!gauge(i)) return true;
        return torque() || derivedPower() || smoothing() || !factoryUnit() || customRange("torque") || customRange("power");
    }
    public static double toKW(double value, int unit) { return unit == 0 ? value : unit == 1 ? value / 1.3596216173 : unit == 2 ? value / 1.3410221338272095 : -1; }
    public static double fromKW(double value, int unit) { return unit == 0 ? value : unit == 1 ? value * 1.3596216173 : unit == 2 ? value * 1.3410221338272095 : -1; }
}
