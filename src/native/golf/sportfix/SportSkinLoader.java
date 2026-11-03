package golf.sportfix;
import de.vw.mib.skin.SkinClassLoader;
import de.vw.mib.viewmanager.internal.ViewHandler;

/** Constructor-injected in a new Car factory; the existing loader is untouched. */
public final class SportSkinLoader implements SkinClassLoader {
    private final SkinClassLoader original;
    private final SportPluginLoader plugin;
    private boolean failed;
    public SportSkinLoader(SkinClassLoader value, SportPluginLoader loader) { original = value; plugin = loader; }
    private ViewHandler custom(String name) {
        if (failed || original.getSkin() != 5 || !"generated.de.vw.mib.view.internal.Csd".equals(name)) return null;
        try {
            ViewHandler result = (ViewHandler) plugin.loadClass("golf.sporttrial.CsdTorque").newInstance();
            SportsBootstrap.status("view-created:configured");
            return result;
        } catch (Throwable error) {
            failed = true;
            SportsBootstrap.status("failed:view:" + error.getClass().getName());
            return null;
        }
    }
    public ViewHandler getViewHandler(String name) { ViewHandler value = custom(name); return value == null ? original.getViewHandler(name) : value; }
    public ViewHandler getViewHandler(String name, String container) { return original.getViewHandler(name, container); }
    public int getSkin() { return original.getSkin(); }
    public boolean unloadDataForClass(String name) { return original.unloadDataForClass(name); }
}
