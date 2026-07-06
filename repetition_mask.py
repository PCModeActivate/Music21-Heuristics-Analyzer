#!/usr/bin/env python
"""
repetition_mask.py

Rhythm-repetition score for the v2.9.x sectioning pipeline (the m.54 fix).

Problem this solves:
    Inside a periodic figuration (e.g. Alto Sax m.54: three eighths + an
    eighth rest, repeating every 2 qn), the rhythm-SSM novelty is correctly
    low, but note-anchored candidates (LBDM rest term + following-gap)
    fire identically at every cell and bypass the SSM entirely.  Peak
    grouping then picks an essentially arbitrary winner among near-tied
    peaks.  The fix: ask the rhythm features directly "am I inside a
    repeating pattern?" and attenuate note-anchored evidence there.

Definition (fully explainable):
    Let p(t) be the cosine-normalized rhythm feature row at frame t
    (attack / sustain / rest one-hots, so cos(p(t), p(u)) is 1 when the
    two frames are in the same rhythmic state and 0 otherwise).

    For a lag l (in frames) and window W:
        sim_fwd(t, l) = mean_{k in [-W, W]} cos(p(t+k), p(t+l+k))
        sim_back(t, l) = sim_fwd(t-l, l)

    R(t) = max over l in [lag_min, lag_max] of min(sim_fwd, sim_back)

    The min() is the load-bearing part: interior frames of a repeating
    texture look like BOTH their past and their future at the pattern
    period, so R is high.  At the texture's entry the backward similarity
    is low, at its exit the forward similarity is low, so R stays low at
    the edges and boundary candidates there are untouched.

    R(t) is in [0, 1] with absolute meaning: R(t) = 0.9 at lag 2 qn reads
    as "90% of the frames in the window around t are in the same rhythmic
    state as the frames one pattern-period away, on both sides."

Usage in the pipeline (wiring is a separate patch):
    rep = compute_repetition_score(phi_rhythm[i], division)
    ...
    candidate *= (1 - delta_repetition * rep)        # soft attenuator
    selection_score -= gamma_repetition * rep        # selection penalty

    Both deltas default to 0.0 in the pipeline so a run with defaults is
    bit-identical to v2.10-A output (pure A/B).

Choice of lag_max_qn is musical, not technical:
    it is the maximum period that counts as *figuration* (one phrase)
    rather than *phrase repetition* (boundary per repeat).  Default 3.0
    covers 2-qn cells like m.54 without reaching phrase-length periods.
"""

import numpy as np


def _normalize_rows(phi):
    """Cosine-normalize feature rows; zero rows stay zero."""
    norms = np.linalg.norm(phi, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return phi / norms


def _windowed_mean(x, half_window_frames):
    """Centered moving average with edge-shrinking window (no phantom
    similarity leaking past the signal edges)."""
    W = int(half_window_frames)
    if W <= 0:
        return x.copy()
    kernel = np.ones(2 * W + 1)
    num = np.convolve(x, kernel, mode='same')
    den = np.convolve(np.ones_like(x), kernel, mode='same')
    return num / den


def compute_repetition_score(phi_part, division,
                              lag_min_qn=0.5,
                              lag_max_qn=3.0,
                              window_qn=1.0,
                              lag_step_frames=1,
                              return_best_lag=False):
    """
    Per-frame rhythm-repetition score R(t) in [0, 1].

    Args:
        phi_part: (T, D) rhythm feature rows for one part
                  (build_rhythm_feature_vectors output for part i).
        division: frames per quarter note.
        lag_min_qn / lag_max_qn: period search range in quarter notes.
        window_qn: half-window (qn) for local context comparison.
        lag_step_frames: stride through the lag range (1 = every frame lag;
                  raise to speed up on long scores).
        return_best_lag: if True also return, per frame, the lag (in qn)
                  that achieved the max — this is the "because" in the
                  explanation ("R=0.9 because the pattern repeats at 2 qn").

    Returns:
        R (T,) float array, or (R, best_lag_qn) if return_best_lag.
    """
    T = phi_part.shape[0]
    Pn = _normalize_rows(np.asarray(phi_part, dtype=float))

    lag_lo = max(int(round(lag_min_qn * division)), 1)
    lag_hi = max(int(round(lag_max_qn * division)), lag_lo)
    W = max(int(round(window_qn * division)), 0)

    R = np.zeros(T)
    best_lag = np.zeros(T)

    for lag in range(lag_lo, lag_hi + 1, max(int(lag_step_frames), 1)):
        if lag >= T:
            break
        # cos(p(t), p(t+lag)) for t in [0, T-lag)
        c = np.einsum('ij,ij->i', Pn[:T - lag], Pn[lag:])
        c_win = _windowed_mean(c, W)

        # sim_fwd[t] = local similarity between context(t) and context(t+lag)
        sim_fwd = np.zeros(T)
        sim_fwd[:T - lag] = c_win
        # sim_back[t] = sim_fwd[t - lag]
        sim_back = np.zeros(T)
        sim_back[lag:] = c_win

        both = np.minimum(sim_fwd, sim_back)
        better = both > R
        R[better] = both[better]
        best_lag[better] = lag / float(division)

    if return_best_lag:
        return R, best_lag
    return R


def repetition_multiplier(R, delta_repetition):
    """Soft attenuator (1 - delta * R), clipped at 0.

    delta_repetition = 0.0 -> identity (pipeline default; pure A/B).
    """
    return np.clip(1.0 - float(delta_repetition) * R, 0.0, 1.0)


def explain_repetition_at(R, best_lag_qn, t_qn, division):
    """One-sentence explanation of the score at a time point."""
    i = min(max(int(round(t_qn * division)), 0), len(R) - 1)
    if R[i] < 1e-6:
        return (f"t={t_qn:.2f} qn: R=0.00 -- no rhythmic repetition "
                f"detected in the lag range.")
    return (f"t={t_qn:.2f} qn: R={R[i]:.2f} -- local rhythm matches the "
            f"material {best_lag_qn[i]:.2f} qn away on both sides "
            f"(interior of a repeating pattern).")
