#!/usr/bin/env python
"""
repetition_mask.py  (v2: rest-backed rule)

Rhythm-repetition score for the v2.10 sectioning pipeline (the m.54 fix).

Problem this solves:
    Inside a periodic figuration (e.g. Alto Sax m.54: three slurred
    eighths + an eighth rest, repeating every 2 qn), every cell produces
    identical boundary evidence -- slur endpoints, rest gaps, novelty at
    the cell seams -- and peak grouping picks an essentially arbitrary
    winner among near-tied peaks.  The fix: score each frame for "am I
    inside a repeating pattern?" and attenuate pattern-periodic evidence
    there, leaving the texture's genuine edges alone.

Definition (fully explainable):
    Let p(t) be the cosine-normalized rhythm feature row at frame t
    (attack / sustain / rest one-hots, so cos(p(t), p(u)) is 1 when the
    two frames are in the same rhythmic state, 0 otherwise).

    For lag l and centered window W:
        sim_fwd(t, l)  = mean_{k in [-W, W]} cos(p(t+k), p(t+l+k))
        sim_back(t, l) = sim_fwd(t-l, l)
        rest_back(t,l) = fraction of rest frames in the window around t-l

    R(t) = max over l in [lag_min, lag_max] of
               min( sim_fwd(t,l), max(sim_back(t,l), rest_back(t,l)) )

    The min() protects genuine edges: interior frames look like BOTH
    their past and their future at the pattern period.  The rest_back
    term (v2) is the silence-behind rule: if the pattern continues ahead
    and what lies behind at the period is SILENCE, the frame is treated
    as pattern-interior too -- a phrase cannot END one cell after a rest;
    the breath already happened in the rest.  The rule is deliberately
    one-sided: silence AHEAD never counts as repetition, because a
    pattern's last cell before a rest is a legitimate phrase end.

    R(t) in [0,1] has absolute meaning: R=0.9 at lag 2 qn reads as "90%
    of the frames around t match the frames one period away (or the
    period-back context is rest), on both sides."

Usage in the pipeline (wired via patch scripts):
    R masks, POST-normalization: rhythm novelty and the slur-endpoint
    boost inside compute_per_part_boundary_signal, plus following-gap
    evidence in the selection layer.  Chroma novelty, long-note
    arrivals, LBDM, and structural bumps are deliberately unmasked.
    delta_repetition=0.0 (default) disables everything.

Choice of lag_max_qn is musical, not technical: it is the maximum
period that counts as *figuration* (one phrase) rather than *phrase
repetition* (boundary per repeat).  Default 3.0.
"""

import numpy as np

# Column layout of build_rhythm_feature_vectors rows: [attack, sustain, rest]
REST_CHANNEL = 2


def _normalize_rows(phi):
    """Cosine-normalize feature rows; zero rows stay zero."""
    norms = np.linalg.norm(phi, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return phi / norms


def _windowed_mean(x, half_window_frames):
    """Centered moving average with edge-shrinking window."""
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
                              rest_backed=True,
                              return_best_lag=False):
    """
    Per-frame rhythm-repetition score R(t) in [0, 1].

    Args:
        phi_part: (T, D) rhythm feature rows for one part.
        division: frames per quarter note.
        lag_min_qn / lag_max_qn: period search range in quarter notes.
        window_qn: half-window (qn) for local context comparison.
        lag_step_frames: stride through the lag range.
        rest_backed: enable the silence-behind rule (v2).  When True, a
            frame whose period-back context is rest counts as interior
            when the pattern continues ahead.
        return_best_lag: if True also return, per frame, the lag (qn)
            that achieved the max -- the "because" in the explanation.

    Returns:
        R (T,) float array, or (R, best_lag_qn) if return_best_lag.
    """
    T = phi_part.shape[0]
    phi = np.asarray(phi_part, dtype=float)
    Pn = _normalize_rows(phi)

    lag_lo = max(int(round(lag_min_qn * division)), 1)
    lag_hi = max(int(round(lag_max_qn * division)), lag_lo)
    W = max(int(round(window_qn * division)), 0)

    # Windowed rest fraction (for the silence-behind rule).
    if rest_backed:
        rest_ind = (Pn[:, REST_CHANNEL] > 0.9).astype(float)
        rest_win = _windowed_mean(rest_ind, W)

    R = np.zeros(T)
    best_lag = np.zeros(T)

    for lag in range(lag_lo, lag_hi + 1, max(int(lag_step_frames), 1)):
        if lag >= T:
            break
        c = np.einsum('ij,ij->i', Pn[:T - lag], Pn[lag:])
        c_win = _windowed_mean(c, W)

        sim_fwd = np.zeros(T)
        sim_fwd[:T - lag] = c_win
        sim_back = np.zeros(T)
        sim_back[lag:] = c_win

        back_or_rest = sim_back
        if rest_backed:
            rest_back = np.zeros(T)
            rest_back[lag:] = rest_win[:T - lag]
            back_or_rest = np.maximum(sim_back, rest_back)

        both = np.minimum(sim_fwd, back_or_rest)
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
            f"(or the period-back context is rest); interior of a "
            f"repeating pattern.")
