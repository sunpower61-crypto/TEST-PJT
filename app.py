import io
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.signal import find_peaks, savgol_filter


def generate_dummy_oes_data(
    n_steps: int = 300,
    wavelength_start: int = 200,
    wavelength_end: int = 900,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OES data for quick testing.

    Rows represent process time steps and columns represent wavelengths (nm).
    The generated spectra include baseline drift, multiple peak families, temporal
    modulation, and an endpoint-like regime change.
    """
    rng = np.random.default_rng(seed)
    wavelengths = np.arange(wavelength_start, wavelength_end + 1)
    time = np.arange(n_steps)

    # Build a slowly drifting baseline across wavelength and time.
    baseline_w = 40 + 10 * np.sin((wavelengths - wavelength_start) / 100)
    baseline_t = 1 + 0.15 * np.sin(time / 30)

    # Representative emission lines (nm): F, O, Ar, Cl, CFx-like bands.
    line_defs = {
        "F": [703, 685],
        "O": [777, 845],
        "Ar": [750, 811],
        "Cl": [837, 726],
        "CFx": [248, 288],
    }

    data = np.zeros((n_steps, wavelengths.size), dtype=float)

    # Process regime transition to mimic etch endpoint dynamics.
    transition = 1 / (1 + np.exp(-(time - int(n_steps * 0.65)) / 8))

    for i, t in enumerate(time):
        spectrum = baseline_w * baseline_t[i]

        # Add peaks for each species with temporal behavior.
        for species, centers in line_defs.items():
            for center in centers:
                width = 1.8 + 0.8 * rng.random()
                amp_base = {
                    "F": 150,
                    "O": 180,
                    "Ar": 220,
                    "Cl": 120,
                    "CFx": 90,
                }[species]

                # Species-specific trend over etch time.
                if species == "Ar":
                    amp = amp_base * (1.0 + 0.08 * np.sin(t / 22))
                elif species in {"F", "CFx"}:
                    amp = amp_base * (1.2 - 0.5 * transition[i] + 0.1 * np.sin(t / 18))
                elif species == "Cl":
                    amp = amp_base * (0.9 + 0.6 * transition[i])
                else:  # O
                    amp = amp_base * (1.0 + 0.25 * np.sin(t / 35) - 0.15 * transition[i])

                spectrum += amp * np.exp(-0.5 * ((wavelengths - center) / width) ** 2)

        # Add random sensor noise.
        noise = rng.normal(0, 6, size=wavelengths.size)
        data[i, :] = spectrum + noise

    df = pd.DataFrame(data, columns=wavelengths)
    df.insert(0, "Step", time)
    return df


def apply_smoothing(
    spectrum_df: pd.DataFrame,
    method: str = "Moving Average",
    ma_window: int = 5,
    sg_window: int = 9,
    sg_polyorder: int = 2,
) -> pd.DataFrame:
    """Denoise OES signals across time for each wavelength channel."""
    values = spectrum_df.copy()

    if method == "Moving Average":
        smoothed = values.rolling(window=max(1, ma_window), min_periods=1).mean()
    elif method == "Savitzky-Golay":
        # Savitzky-Golay preserves peak shape while smoothing high-frequency noise.
        window = max(3, sg_window)
        if window % 2 == 0:
            window += 1
        poly = min(max(1, sg_polyorder), window - 1)
        smoothed_arr = savgol_filter(values.to_numpy(), window_length=window, polyorder=poly, axis=0)
        smoothed = pd.DataFrame(smoothed_arr, columns=values.columns, index=values.index)
    else:
        smoothed = values

    return smoothed


def baseline_correction(spectrum_df: pd.DataFrame, quantile: float = 0.1) -> pd.DataFrame:
    """Remove background emission by subtracting a low-intensity baseline per row.

    목적:
    - 플라즈마 발광 신호에는 장비/광학계 배경 노이즈가 섞여 있습니다.
    - 각 시간 스텝의 스펙트럼에서 하위 분위수(예: 10%)를 baseline으로 가정해 제거하면,
      상대적으로 순수한 피크 성분을 강조할 수 있습니다.
    """
    baseline = spectrum_df.quantile(quantile, axis=1)
    corrected = spectrum_df.sub(baseline, axis=0)
    corrected = corrected.clip(lower=0)
    return corrected


def find_nearest_wavelength(columns: List[float], target_nm: float) -> float:
    arr = np.array(columns, dtype=float)
    idx = np.abs(arr - target_nm).argmin()
    return float(arr[idx])


def calculate_actinometry_ratio(
    processed_df: pd.DataFrame,
    reactive_wavelength: float,
    ar_wavelength: float,
    epsilon: float = 1e-9,
) -> pd.Series:
    """Calculate relative radical density proxy using actinometry ratio.

    목적:
    - Actinometry는 반응성 종의 발광 강도(I_reactive)를 기준 가스(일반적으로 Ar)의
      발광 강도(I_Ar)로 나누어, 플라즈마 상태 변화에 따른 상대 밀도 변화를 추정합니다.
    - 절대 밀도는 아니지만 공정 모니터링/트렌드 비교에 매우 유용합니다.
    """
    reactive_nm = find_nearest_wavelength(list(processed_df.columns), reactive_wavelength)
    ar_nm = find_nearest_wavelength(list(processed_df.columns), ar_wavelength)

    ratio = processed_df[reactive_nm] / (processed_df[ar_nm] + epsilon)
    ratio.name = f"Actinometry_{reactive_nm:.1f}/{ar_nm:.1f}"
    return ratio


def detect_epd(
    intensity_series: pd.Series,
    smooth_window: int = 11,
    threshold_scale: float = 2.0,
) -> Tuple[int, pd.Series, pd.Series]:
    """Detect endpoint candidate using first/second derivatives.

    목적:
    - End Point Detection(EPD)은 식각 완료 시점 부근에서 특정 파장 강도의 급격한
      변화(감소/증가 또는 곡률 변화)를 찾는 알고리즘입니다.
    - 본 구현은 시계열을 먼저 평활화한 뒤 1차/2차 미분을 계산하여,
      곡률(|2차 미분|)이 통계적 임계값을 초과하는 최초 지점을 endpoint 후보로 선택합니다.
    """
    arr = intensity_series.to_numpy(dtype=float)
    w = max(5, smooth_window)
    if w % 2 == 0:
        w += 1
    if w >= len(arr):
        w = len(arr) - 1 if len(arr) % 2 == 0 else len(arr)
    if w < 5:
        smooth = arr
    else:
        smooth = savgol_filter(arr, window_length=w, polyorder=2)

    first_derivative = np.gradient(smooth)
    second_derivative = np.gradient(first_derivative)

    abs_second = np.abs(second_derivative)
    threshold = abs_second.mean() + threshold_scale * abs_second.std()
    candidates = np.where(abs_second > threshold)[0]

    if len(candidates) > 0:
        epd_idx = int(candidates[0])
    else:
        epd_idx = int(np.argmax(abs_second))

    return epd_idx, pd.Series(first_derivative, index=intensity_series.index), pd.Series(second_derivative, index=intensity_series.index)


def read_uploaded_oes(file_obj) -> pd.DataFrame:
    name = file_obj.name.lower()
    bytes_data = file_obj.read()

    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(bytes_data))
    else:
        # txt/tsv fallback with automatic separator inference.
        df = pd.read_csv(io.BytesIO(bytes_data), sep=None, engine="python")

    if "Step" not in df.columns:
        df.insert(0, "Step", np.arange(len(df)))

    # Convert spectral columns to numeric wavelengths if possible.
    rename_map = {}
    for c in df.columns:
        if c == "Step":
            continue
        try:
            rename_map[c] = float(c)
        except Exception:
            pass
    df = df.rename(columns=rename_map)

    return df


def build_default_species() -> Dict[str, float]:
    return {
        "F": 703.0,
        "O": 777.0,
        "Ar": 750.0,
        "Cl": 837.0,
        "CFx": 248.0,
    }


st.set_page_config(page_title="OES Plasma Monitor", layout="wide")
st.title("Dry Etching OES 분석 대시보드")
st.caption("OES 스펙트럼 전처리, 피크 분석, Actinometry, EPD를 한 번에 확인합니다.")

with st.sidebar:
    st.header("데이터 입력")
    uploaded = st.file_uploader("OES CSV/TXT 업로드", type=["csv", "txt", "tsv"])
    use_dummy = st.checkbox("더미 데이터 사용", value=uploaded is None)

    st.markdown("---")
    st.subheader("전처리 옵션")
    smooth_method = st.selectbox("노이즈 제거", ["None", "Moving Average", "Savitzky-Golay"], index=1)
    ma_window = st.slider("MA Window", 1, 31, 5, 2)
    sg_window = st.slider("SG Window (odd)", 5, 51, 11, 2)
    sg_poly = st.slider("SG Polyorder", 1, 5, 2)
    baseline_q = st.slider("Baseline Quantile", 0.0, 0.5, 0.1, 0.01)

if uploaded is not None and not use_dummy:
    raw_df = read_uploaded_oes(uploaded)
else:
    raw_df = generate_dummy_oes_data()

spectral_cols = [c for c in raw_df.columns if c != "Step"]
raw_spectral = raw_df[spectral_cols].astype(float)

processed = apply_smoothing(
    raw_spectral,
    method=smooth_method,
    ma_window=ma_window,
    sg_window=sg_window,
    sg_polyorder=sg_poly,
)
processed = baseline_correction(processed, quantile=baseline_q)

steps = raw_df["Step"]

st.subheader("데이터 미리보기")
st.dataframe(raw_df.head(10), use_container_width=True)

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Spectrum View (특정 Step의 파장 스펙트럼)")
    step_idx = st.slider("스펙트럼 확인 Step", 0, len(raw_df) - 1, min(50, len(raw_df) - 1))

    fig_spec = go.Figure()
    fig_spec.add_trace(
        go.Scatter(
            x=np.array(spectral_cols, dtype=float),
            y=processed.iloc[step_idx].to_numpy(),
            mode="lines",
            name=f"Step {step_idx}",
        )
    )
    fig_spec.update_layout(xaxis_title="Wavelength (nm)", yaxis_title="Corrected Intensity")
    st.plotly_chart(fig_spec, use_container_width=True)

    st.markdown("#### Peak Detection")
    peak_prom = st.number_input("Peak Prominence", min_value=0.0, value=20.0, step=1.0)
    peak_distance = st.number_input("Peak Distance", min_value=1, value=5, step=1)

    y = processed.iloc[step_idx].to_numpy()
    peaks, props = find_peaks(y, prominence=peak_prom, distance=peak_distance)
    peak_table = pd.DataFrame(
        {
            "Wavelength": np.array(spectral_cols, dtype=float)[peaks],
            "Intensity": y[peaks],
            "Prominence": props.get("prominences", np.zeros(len(peaks))),
        }
    ).sort_values("Intensity", ascending=False)
    st.dataframe(peak_table.head(20), use_container_width=True)

with col2:
    st.subheader("Species Mapping & Time Trend")
    st.caption("관심 Radical/Ion 파장 입력 (쉼표로 다중 입력 가능)")

    default_map = build_default_species()
    species_input = st.text_area(
        "Species Mapping (예: F:703, O:777, Ar:750, Cl:837, CFx:248)",
        value=", ".join([f"{k}:{v}" for k, v in default_map.items()]),
    )

    species_map: Dict[str, float] = {}
    for token in species_input.split(","):
        if ":" not in token:
            continue
        k, v = token.split(":", 1)
        k = k.strip()
        try:
            species_map[k] = float(v.strip())
        except ValueError:
            continue

    selected_species = st.multiselect("시계열 추적 Species", options=list(species_map.keys()), default=list(species_map.keys())[:3])

    fig_trend = go.Figure()
    for sp in selected_species:
        target = species_map[sp]
        nearest = find_nearest_wavelength(list(processed.columns), target)
        fig_trend.add_trace(
            go.Scatter(x=steps, y=processed[nearest], mode="lines", name=f"{sp} ({nearest:.1f} nm)")
        )

    fig_trend.update_layout(xaxis_title="Step", yaxis_title="Corrected Intensity")
    st.plotly_chart(fig_trend, use_container_width=True)

st.markdown("---")
st.subheader("Actinometry Trend")

c1, c2 = st.columns(2)
with c1:
    reactive_nm = st.number_input("Reactive Line (nm)", value=703.0, step=1.0)
with c2:
    ar_nm = st.number_input("Reference Ar Line (nm)", value=750.0, step=1.0)

ratio = calculate_actinometry_ratio(processed, reactive_nm, ar_nm)
fig_ratio = go.Figure()
fig_ratio.add_trace(go.Scatter(x=steps, y=ratio, mode="lines", name=ratio.name))
fig_ratio.update_layout(xaxis_title="Step", yaxis_title="I_reactive / I_Ar")
st.plotly_chart(fig_ratio, use_container_width=True)

st.markdown("---")
st.subheader("EPD (End Point Detection)")

epd_target = st.number_input("EPD 모니터링 파장 (nm)", value=703.0, step=1.0)
epd_nearest = find_nearest_wavelength(list(processed.columns), epd_target)
epd_series = processed[epd_nearest]

epd_idx, d1, d2 = detect_epd(epd_series, smooth_window=11, threshold_scale=2.0)

fig_epd = go.Figure()
fig_epd.add_trace(go.Scatter(x=steps, y=epd_series, mode="lines", name=f"Intensity {epd_nearest:.1f}nm"))
fig_epd.add_vline(x=steps.iloc[epd_idx], line_dash="dash", line_color="red")
fig_epd.update_layout(xaxis_title="Step", yaxis_title="Intensity")
st.plotly_chart(fig_epd, use_container_width=True)

fig_deriv = go.Figure()
fig_deriv.add_trace(go.Scatter(x=steps, y=d1, mode="lines", name="1st Derivative"))
fig_deriv.add_trace(go.Scatter(x=steps, y=d2, mode="lines", name="2nd Derivative"))
fig_deriv.add_vline(x=steps.iloc[epd_idx], line_dash="dash", line_color="red")
fig_deriv.update_layout(xaxis_title="Step", yaxis_title="Derivative")
st.plotly_chart(fig_deriv, use_container_width=True)

st.success(f"EPD 후보 시점: Step {int(steps.iloc[epd_idx])} (파장 {epd_nearest:.1f} nm)")
