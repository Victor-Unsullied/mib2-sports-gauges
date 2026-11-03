package golf.sporttrial;

import de.vw.mib.animation.easing.EasingParams;
import de.vw.mib.widgets.Instruments;
import de.vw.mib.widgets.models.InstrumentsModel;

/** Use the native frame animator; full-scale travel takes 500 ms. */
public final class NeedleSmoothing {
    private NeedleSmoothing() { }

    public static void setValue(InstrumentsModel model, int target, boolean valid) {
        Instruments gauge = (Instruments) model;
        // Repeated polling must not restart an in-progress sweep.
        if (valid && target == gauge.get_value()) return;
        int current = gauge.isValueChangeAnimationRunning()
                ? gauge.get_valueOut() : gauge.get_value();
        // Native valueChanged starts from the previous target. Rebase to the
        // rendered position first so a new reading cannot jump the pointer.
        if (gauge.isValueChangeAnimationRunning()) {
            gauge.disableAnimations();
            try { gauge.set_value(current); }
            finally { gauge.enableAnimations(); }
        }
        if (!valid) {
            if (gauge.isValueChangeAnimationRunning()) gauge.stopInternalAnimations();
            gauge.disableAnimations();
            try { gauge.set_value(target); }
            finally { gauge.enableAnimations(); }
            return;
        }
        int span = gauge.get_valueMax() - gauge.get_valueMin();
        int distance = Math.abs(target - current);
        int duration = span <= 0 ? 1 : Math.max(1, (int) (500L * distance / span));
        EasingParams[] original = gauge.get_easing();
        int count = original == null ? 0 : original.length;
        EasingParams[] easing = new EasingParams[Math.max(count, 16)];
        if (count > 0) System.arraycopy(original, 0, easing, 0, count);
        // Clone the array and replace only value motion, leaving shared skin
        // easings, startup sweeps, Boost and temperature needles untouched.
        easing[15] = new EasingParams(EasingParams.EASING_KIND_IN,
                EasingParams.EASING_CLASS_LINEAR, duration, 0);
        gauge.set_easing(easing);
        gauge.set_value(target);
    }
}
