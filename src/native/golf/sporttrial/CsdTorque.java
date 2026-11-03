package golf.sporttrial;
import golf.sportconfig.GaugeOptions;

import de.vw.mib.datapool.LocalListItemControl;
import de.vw.mib.hmi.internal.ServiceManagerCommon;
import de.vw.mib.timer.Invoker;
import de.vw.mib.timer.Timer;
import de.vw.mib.view.internal.CloneData;
import de.vw.mib.widgets.FlowList;
import de.vw.mib.widgets.ListItem;
import de.vw.mib.widgets.interfaces.WidgetCloneable;
import de.vw.mib.widgets.models.InstrumentsModel;
import de.vw.mib.widgets.models.ListItemModel;
import de.vw.mib.widgets.models.TextAreaModel;
import de.vw.mib.widgets.models.WidgetModel;
import generated.de.vw.mib.view.internal.Csd;
import generated.de.vw.mib.view.internal.SkinLiteralPool;

/**
 * PC-only trial: append a sixth native ListItem to all three original lists.
 * All five original templates, model properties, images and handlers remain.
 * Uses the native widget clone factory and native HMI invoker, not a web UI.
 */
public final class CsdTorque extends Csd {
    private static final int[] LISTS = {9, 18, 27};
    private static final int[] POWER_TEMPLATES = {13, 21, 28};
    // Exact native clone-master indices, in Boost/G-meter/Coolant/Power/Oil order.
    private static final int[][] GAUGE_TEMPLATES = {{10,11,12,13,14},{23,19,20,21,22},{30,31,32,28,29}};
    private final CloneData[] torqueMasters = new CloneData[3];
    private final WidgetModel[][] originalChildren = new WidgetModel[3][];
    private Timer refreshTimer;
    private boolean refreshing;
    private boolean refreshFailed;

    private int powerUnit() { return GaugeOptions.powerUnit(getInteger(21953)); }
    public Object getInternObject(int index, CloneData data) {
        if (index == 6) {
            int unit = powerUnit();
            return unit == 0 ? "kW" : unit == 1 ? "PS" : unit == 2 ? "hp" : "";
        }
        return super.getInternObject(index, data);
    }

    protected void initWidgets() {
        super.initWidgets();
        if (!GaugeOptions.torque()) { refreshPower(); applyGaugeFlags(); return; }
        // A handler may be initialized again after native deinit/recreate.
        // Old widget arrays must never be used for a later failed append.
        for (int tube = 0; tube < originalChildren.length; tube++) originalChildren[tube] = null;
        try {
            for (int tube = 0; tube < 3; tube++) {
                FlowList list = (FlowList) cd0.widgets[LISTS[tube]];
                originalChildren[tube] = list.getChildren();
                if (originalChildren[tube].length != 5) {
                    throw new IllegalStateException("Expected five original Sport templates");
                }
                WidgetCloneable source = (WidgetCloneable) cd0.widgets[POWER_TEMPLATES[tube]];
                CloneData powerMaster = ((CloneData) source.getCloneData()).master;
                CloneData previousFirst = powerMaster.next;
                WidgetCloneable copy;
                try {
                    copy = createWidgetCloneable(source);
                } catch (Throwable failure) {
                    // The native clone builder links before initialization. A
                    // failing initializer may therefore leave a half-built node
                    // even though createWidgetCloneable never returned it.
                    rollbackCreatedPowerClones(powerMaster, previousFirst);
                    throw failure;
                }
                CloneData data = (CloneData) copy.getCloneData();
                // This becomes an independent template. Subsequent FlowList clones
                // inherit this master, rather than the original power master.
                CloneData.remove(data.master, data);
                data.master = data;
                data.next = null;
                torqueMasters[tube] = data;
                markTorque(data, tube);
                WidgetModel[] children = new WidgetModel[6];
                System.arraycopy(originalChildren[tube], 0, children, 0, 5);
                children[5] = data.widgets[0];
                list.setChildren(children);
            }
            refreshTorque();
            System.out.println("[GolfSportTrial] Appended torque; original five choices retained in all tubes");
        } catch (Throwable failure) {
            System.out.println("[GolfSportTrial] Torque append failed; restoring original list children: " + failure);
            restoreOriginalChildren();
            disposeTorqueMasters();
        }
        applyGaugeFlags();
    }

    private void applyGaugeFlag(CloneData data) {
        if (data == null || data.widgets == null || data.widgets.length == 0) return;
        if (torqueTube(data) >= 0) {
            if (!GaugeOptions.torque()) data.widgets[0].set_enabled(false);
            return;
        }
        if (cd0 == null || cd0.widgets == null) return;
        for (int tube=0;tube<3;tube++) for (int kind=0;kind<5;kind++) {
            int index=GAUGE_TEMPLATES[tube][kind];
            if (GaugeOptions.gauge(kind) || cd0.widgets.length<=index || !(cd0.widgets[index] instanceof WidgetCloneable)) continue;
            CloneData master=(CloneData)((WidgetCloneable)cd0.widgets[index]).getCloneData();
            if (master!=null && master.master==data.master) data.widgets[0].set_enabled(false);
        }
    }
    private void applyGaugeFlags() {
        if (cd0 == null || cd0.widgets == null) return;
        for (int tube=0;tube<3;tube++) {
            for (int kind=0;kind<5;kind++) {
                int index=GAUGE_TEMPLATES[tube][kind];
                if (GaugeOptions.gauge(kind) || cd0.widgets.length<=index || !(cd0.widgets[index] instanceof WidgetCloneable)) continue;
                CloneData data=(CloneData)((WidgetCloneable)cd0.widgets[index]).getCloneData();
                if (data!=null) data=data.master;
                while (data!=null) { data.widgets[0].set_enabled(false); data=data.next; }
            }
            if (!GaugeOptions.anyGauge() && cd0.widgets.length>LISTS[tube] && cd0.widgets[LISTS[tube]]!=null)
                cd0.widgets[LISTS[tube]].set_visible(false);
        }
    }
    public void datapoolValueChanged(int id) { super.datapoolValueChanged(id); applyGaugeFlags(); }

    private int torqueTube(CloneData data) {
        if (data == null) return -1;
        for (int tube = 0; tube < torqueMasters.length; tube++) {
            if (torqueMasters[tube] != null && data.master == torqueMasters[tube]) return tube;
        }
        return -1;
    }

    private void rollbackCreatedPowerClones(CloneData master, CloneData previousFirst) {
        while (master.next != null && master.next != previousFirst) {
            CloneData incomplete = master.next;
            // Restore the original chain before attempting fallible cleanup.
            CloneData.remove(master, incomplete);
            try {
                destroyWidgetCloneable((WidgetCloneable) incomplete.widgets[0]);
            } catch (Throwable cleanupFailure) {
                System.out.println("[GolfSportTrial] Partial clone cleanup failed after detaching: " + cleanupFailure);
            }
        }
    }

    protected void initCloneData(CloneData data) {
        // The saved native power subtree supplies compatible widget/UI/controller
        // types and initialization. Only this independent new template is retitled.
        int tube = torqueTube(data);
        if (tube >= 0) {
            // Generated initialization checks ownership and reads unit labels via
            // cdOf(data, originalPowerMaster). Present that original owner only
            // during initialization, then restore our independent clone lineage.
            CloneData independentMaster = data.master;
            CloneData power = (CloneData) ((WidgetCloneable)
                    cd0.widgets[POWER_TEMPLATES[tube]]).getCloneData();
            data.master = power.master;
            try {
                super.initCloneData(data);
            } finally {
                data.master = independentMaster;
            }
            markTorque(data, tube);
            paintTorque(data);
        } else { super.initCloneData(data); if (powerTube(data) >= 0) paintPower(data); }
        applyGaugeFlag(data);
    }

    protected void transferScriptResults(CloneData data) {
        if (torqueTube(data) >= 0) paintTorque(data);
        else { super.transferScriptResults(data); if (powerTube(data) >= 0) paintPower(data); }
        applyGaugeFlag(data);
    }

    protected void activateCloneData(CloneData data) {
        if (torqueTube(data) >= 0) paintTorque(data);
        else { super.activateCloneData(data); if (powerTube(data) >= 0) paintPower(data); }
        applyGaugeFlag(data);
    }

    protected void deactivateCloneData(CloneData data) {
        if (torqueTube(data) < 0) super.deactivateCloneData(data);
    }

    private void markTorque(CloneData data, int tube) {
        for (int index = 0; index < data.widgets.length; index++) {
            data.widgets[index].set_targetId(187000 + tube * 16 + index);
        }
        data.widgets[0].set_name("ListItem_Torque_Tube" + tube);
        data.widgets[0].set_enabled(true);
        // The new master is deliberately outside the original power chain, so
        // the generated power-control registration loop does not configure it.
        ((ListItem) data.widgets[0]).setListItemControl(new LocalListItemControl(1));
    }


    private int powerTube(CloneData data) {
        if (data == null || cd0 == null || cd0.widgets == null) return -1;
        for (int tube = 0; tube < POWER_TEMPLATES.length; tube++) {
            if (cd0.widgets.length <= POWER_TEMPLATES[tube]) continue;
            if (!(cd0.widgets[POWER_TEMPLATES[tube]] instanceof WidgetCloneable)) continue;
            CloneData source = (CloneData) ((WidgetCloneable) cd0.widgets[POWER_TEMPLATES[tube]]).getCloneData();
            if (source != null && source.master == data.master) return tube;
        }
        return -1;
    }

    private CloneData powerMaster(int tube) {
        if (cd0 == null || cd0.widgets == null || cd0.widgets.length <= POWER_TEMPLATES[tube]
            || !(cd0.widgets[POWER_TEMPLATES[tube]] instanceof WidgetCloneable)) return null;
        CloneData source = (CloneData) ((WidgetCloneable) cd0.widgets[POWER_TEMPLATES[tube]]).getCloneData();
        return source == null ? null : source.master;
    }

    private static void setReading(InstrumentsModel model, int value, boolean valid) {
        if (GaugeOptions.smoothing()) NeedleSmoothing.setValue(model, value, valid);
        else model.set_value(value);
    }
    private void paintPower(CloneData data) {
        // Preserve the complete original native Power path when no override is requested.
        if (!GaugeOptions.derivedPower() && GaugeOptions.factoryUnit() && !GaugeOptions.smoothing() && !GaugeOptions.customRange("power")) return;
        WidgetModel[] widgets = data.widgets;
        if (widgets.length != 5) throw new IllegalStateException("Native Power subtree changed");
        int nativeUnit = getInteger(21953);
        int selectedUnit = GaugeOptions.powerUnit(nativeUnit);
        boolean derived = GaugeOptions.derivedPower();
        boolean valid;
        double kilowatts;
        double maxKW;
        if (derived) {
            synchronized (NativeSportTelemetry.class) {
                valid = !refreshFailed && NativeSportTelemetry.isTorqueValid();
                kilowatts = NativeSportTelemetry.getPowerValue(null) / 1.3410221338272095;
            }
            maxKW = 240.0 / 1.3410221338272095;
        } else {
            valid = !refreshFailed && getBoolean(46476) && getBoolean(37735);
            kilowatts = GaugeOptions.toKW(getInteger(64028), nativeUnit);
            maxKW = GaugeOptions.toKW(getInteger(15296), nativeUnit);
        }
        valid = valid && selectedUnit >= 0 && selectedUnit <= 2 && kilowatts >= 0 && maxKW > 0;
        int maximum = (int)Math.round(GaugeOptions.fromKW(maxKW, selectedUnit));
        if (maximum <= 0 || maximum > 999) { maximum = 240; valid = false; }
        int minimum = GaugeOptions.lowerLimit("power", 0);
        maximum = GaugeOptions.upperLimit("power", maximum);
        int actual = (int)GaugeOptions.fromKW(kilowatts, selectedUnit);
        actual = Math.max(minimum, Math.min(maximum, actual));
        InstrumentsModel gauge = (InstrumentsModel)widgets[1];
        gauge.set_scaleParams(SkinLiteralPool.INT__ARRAY1_23);
        gauge.set_scaleValues(new int[]{minimum, maximum});
        gauge.set_scaleStrokeAngles(SkinLiteralPool.INT__ARRAY1_76);
        gauge.set_scaleStrokeTypes(SkinLiteralPool.INT__ARRAY1_75);
        gauge.set_warningZoneAngles(SkinLiteralPool.INT__ARRAY1_15);
        gauge.set_valueMin(minimum); gauge.set_valueMax(maximum);
        setReading(gauge, valid ? actual : minimum, valid);
        ((TextAreaModel)widgets[2]).set_text(ServiceManagerCommon.fixFormat.fmtPower7Segment(888));
        ((TextAreaModel)widgets[3]).set_text(ServiceManagerCommon.fixFormat.fmtPower7Segment(valid ? actual : -1));
        ((TextAreaModel)widgets[4]).set_text(selectedUnit == 0 ? "kW" : selectedUnit == 1 ? "PS" : "hp");
        widgets[0].set_enabled(GaugeOptions.gauge(3) && (derived || getBoolean(37735)));
    }

    private void refreshPower() {
        for (int tube = 0; tube < POWER_TEMPLATES.length; tube++) {
            CloneData data = powerMaster(tube);
            while (data != null) { paintPower(data); data = data.next; }
        }
    }

    private void invalidatePower() {
        for (int tube = 0; tube < POWER_TEMPLATES.length; tube++) {
            CloneData data = powerMaster(tube);
            while (data != null) {
                try { ((TextAreaModel) data.widgets[3]).set_text(ServiceManagerCommon.fixFormat.fmtPower7Segment(-1)); } catch (Throwable ignored) { }
                try { InstrumentsModel gauge = (InstrumentsModel) data.widgets[1]; gauge.set_value(gauge.get_valueMin()); } catch (Throwable ignored) { }
                data = data.next;
            }
        }
    }

    private void paintTorque(CloneData data) {
        WidgetModel[] widgets = data.widgets;
        if (widgets.length != 5) throw new IllegalStateException("Native power subtree shape changed");
        InstrumentsModel gauge = (InstrumentsModel) widgets[1];
        TextAreaModel backgroundDigits = (TextAreaModel) widgets[2];
        TextAreaModel value = (TextAreaModel) widgets[3];
        TextAreaModel unit = (TextAreaModel) widgets[4];
        boolean valid;
        int actual;
        int maximum;
        // Cache writers use this same monitor. Take a coherent input snapshot,
        // then release it before any native widget operation or animation.
        synchronized (NativeSportTelemetry.class) {
            valid = !refreshFailed && NativeSportTelemetry.isFresh() && NativeSportTelemetry.isTorqueValid();
            actual = NativeSportTelemetry.getTorque();
            maximum = NativeSportTelemetry.getMaxTorque();
        }
        // The native Power formatter has three digit positions.
        if (maximum < 50 || maximum > 999) maximum = 350;
        maximum = GaugeOptions.upperLimit("torque", maximum);
        int minimum = GaugeOptions.lowerLimit("torque", 0);
        int display = actual < minimum ? minimum : actual;
        if (display > maximum) display = maximum;
        // These are the exact skin5 Power arrays used by the generated scripts.
        // A native clone initially has empty arrays; copying its widget tree
        // does not execute the Power scripts after detaching its master.
        gauge.set_scaleParams(SkinLiteralPool.INT__ARRAY1_23);
        gauge.set_scaleValues(new int[] {minimum, maximum});
        gauge.set_scaleStrokeAngles(SkinLiteralPool.INT__ARRAY1_76);
        gauge.set_scaleStrokeTypes(SkinLiteralPool.INT__ARRAY1_75);
        gauge.set_warningZoneAngles(SkinLiteralPool.INT__ARRAY1_15);
        int tube = torqueTube(data);
        if (tube >= 0 && cd0 != null && cd0.widgets[POWER_TEMPLATES[tube]] != null) {
            CloneData power = (CloneData) ((WidgetCloneable)
                    cd0.widgets[POWER_TEMPLATES[tube]]).getCloneData();
            gauge.set_performEnterAnimation(((InstrumentsModel)
                    power.widgets[1]).is_performEnterAnimation());
        }
        gauge.set_valueMin(minimum);
        gauge.set_valueMax(maximum);
        setReading(gauge, valid ? display : minimum, valid);
        // Use the same formatter for foreground and ghost digits as native Power.
        backgroundDigits.set_text(ServiceManagerCommon.fixFormat.fmtPower7Segment(888));
        value.set_text(ServiceManagerCommon.fixFormat.fmtPower7Segment(valid ? display : -1));
        boolean calibratedNm = "Nm".equals(System.getProperty("golf.sporttrial.torque.units", "raw"));
        unit.set_text(calibratedNm ? "Nm" : "raw");
        widgets[0].set_enabled(true);
    }

    private void refreshTorque() {
        if (refreshing) return;
        refreshing = true;
        try {
            for (int tube = 0; tube < torqueMasters.length; tube++) {
                CloneData data = torqueMasters[tube];
                while (data != null) {
                    paintTorque(data);
                    data = data.next;
                }
            }
            refreshPower();
        } finally {
            applyGaugeFlags();
            refreshing = false;
        }
    }

    public boolean transferData(ListItemModel item, int listIndex, int dataIndex) {
        if (item instanceof WidgetCloneable) {
            CloneData data = (CloneData) ((WidgetCloneable) item).getCloneData();
            if (torqueTube(data) >= 0) {
                paintTorque(data);
                return true;
            }
        }
        return super.transferData(item, listIndex, dataIndex);
    }

    protected void initScripts() {
        super.initScripts();
        refreshTorque();
    }

    public void updateI18n() {
        super.updateI18n();
        refreshTorque();
    }

    protected void registerDpPropertyListenerOnActivate() {
        super.registerDpPropertyListenerOnActivate();
        refreshFailed = false;
        // Timer dispatches through the existing HMI invoker. No widget mutation
        // runs on the timer or vehicle-data callback thread.
        try {
            refreshTorque();
            refreshTimer = ServiceManagerCommon.timerManager.createTimer(
                "GolfSportTrial.NativeTorque", 250L, true,
                new Runnable() {
                    public void run() {
                        if (isActivated()) {
                            try { refreshTorque(); }
                            catch (Throwable failure) { failRefresh(failure); }
                        }
                    }
                },
                new Invoker() {
                    public void invoke(Runnable runnable) {
                        ServiceManagerCommon.hmiThreadInvoker.invoke(runnable);
                    }
                });
            refreshTimer.start();
        } catch (Throwable failure) {
            failRefresh(failure);
        }
    }

    protected void deregisterDpPropertyListenerOnDeactivate() {
        stopRefreshTimer();
        super.deregisterDpPropertyListenerOnDeactivate();
    }

    private void stopRefreshTimer() {
        if (refreshTimer != null) {
            Timer timer = refreshTimer;
            refreshTimer = null;
            try { timer.stop(); }
            catch (Throwable failure) {
                System.out.println("[GolfSportTrial] Could not stop torque refresh timer: " + failure);
            }
        }
    }

    private void failRefresh(Throwable failure) {
        refreshFailed = true;
        stopRefreshTimer();
        invalidatePower();
        System.out.println("[GolfSportTrial] Torque refresh disabled; originals retained: " + failure);
        // A broken widget must not prevent the other copies from losing their
        // old numeric readings after polling stops. Attempt text and pointer
        // invalidation separately, then continue through every native clone.
        for (int tube = 0; tube < torqueMasters.length; tube++) {
            CloneData data = torqueMasters[tube];
            while (data != null) {
                CloneData next = data.next;
                try { ((TextAreaModel) data.widgets[3]).set_text(
                        ServiceManagerCommon.fixFormat.fmtPower7Segment(-1)); }
                catch (Throwable valueFailure) {
                    System.out.println("[GolfSportTrial] Could not invalidate torque text in tube " + tube + ": " + valueFailure);
                }
                try {
                    InstrumentsModel gauge = (InstrumentsModel) data.widgets[1];
                    gauge.set_value(gauge.get_valueMin());
                } catch (Throwable pointerFailure) {
                    System.out.println("[GolfSportTrial] Could not invalidate torque pointer in tube " + tube + ": " + pointerFailure);
                }
                data = next;
            }
        }
    }

    private void restoreOriginalChildren() {
        for (int tube = 0; tube < 3; tube++) {
            if (originalChildren[tube] != null) {
                try {
                    ((FlowList) cd0.widgets[LISTS[tube]]).setChildren(originalChildren[tube]);
                    originalChildren[tube] = null;
                } catch (Throwable failure) {
                    System.out.println("[GolfSportTrial] Restore failed for tube " + tube + ": " + failure);
                }
            }
        }
    }

    private void disposeTorqueMasters() {
        for (int tube = 0; tube < torqueMasters.length; tube++) {
            CloneData master = torqueMasters[tube];
            if (master != null) {
                torqueMasters[tube] = null;
                try { deinitCloneWidgetAndDestroyClones(master); }
                catch (Throwable failure) {
                    System.out.println("[GolfSportTrial] Clone deinit failed for tube " + tube + ": " + failure);
                }
                try {
                    services.getWidgetTreeBuilder().destroyWidgetTree(getInternalViewId(), master, getUITypes());
                } catch (Throwable failure) {
                    System.out.println("[GolfSportTrial] Clone destroy failed for tube " + tube + ": " + failure);
                }
            }
        }
    }

    protected void deinitCloneWidgetsAndDestroyClones() {
        stopRefreshTimer();
        restoreOriginalChildren();
        disposeTorqueMasters();
        for (int tube = 0; tube < originalChildren.length; tube++) originalChildren[tube] = null;
        super.deinitCloneWidgetsAndDestroyClones();
    }
}
