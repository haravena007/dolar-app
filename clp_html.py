# -*- coding: utf-8 -*-
"""
Generador automático del gráfico animado USD/CLP para Grupo Portfolio.
Pensado para correr vía GitHub Actions cada 15 minutos (sin navegador,
sin interacción manual).

- Histórico diario YTD: yfinance, interval="1d"
- Cotización "hoy": la última vela intradía disponible (interval="15m"),
  reemplazando el cierre diario provisional para que el gráfico refleje
  el precio de mercado más reciente, no solo el cierre del día anterior.

@author: haravena (adaptado para automatización)
"""

import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import yfinance as yf

TICKER = "CLP=X"
FECHA_INICIO = "2026-01-01"
ARCHIVO_SALIDA = "index.html"
TZ_CHILE = ZoneInfo("America/Santiago")


def _aplanar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance a veces devuelve columnas MultiIndex; las aplanamos."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def obtener_historico_diario() -> pd.DataFrame:
    df = yf.download(TICKER, start=FECHA_INICIO, interval="1d", progress=False)
    if df.empty:
        raise ValueError("No se recibieron datos diarios de Yahoo Finance.")
    df = _aplanar_columnas(df).reset_index()
    if "Close" not in df.columns and "Adj Close" in df.columns:
        df.rename(columns={"Adj Close": "Close"}, inplace=True)
    df["Close"] = pd.to_numeric(df["Close"]).astype(float)
    df = df.dropna(subset=["Close"])
    return df[["Date", "Close"]]


def obtener_intradia_hoy() -> pd.DataFrame:
    """Devuelve las velas de 15 min del día de cotización más reciente
    (columna 'Datetime' + 'Close'), para poder calcular apertura/promedio/
    último precio del día, no solo el último valor."""
    intradia = yf.download(TICKER, period="1d", interval="15m", progress=False)
    if intradia.empty:
        # Fin de semana / mercado cerrado: buscamos hacia atrás
        intradia = yf.download(TICKER, period="5d", interval="15m", progress=False)
    if intradia.empty:
        raise ValueError("No se recibieron datos intradía de Yahoo Finance.")

    intradia = _aplanar_columnas(intradia).reset_index()
    if "Close" not in intradia.columns and "Adj Close" in intradia.columns:
        intradia.rename(columns={"Adj Close": "Close"}, inplace=True)

    columna_fecha = "Datetime" if "Datetime" in intradia.columns else intradia.columns[0]
    intradia[columna_fecha] = pd.to_datetime(intradia[columna_fecha])
    intradia = intradia.rename(columns={columna_fecha: "Datetime"})

    # Nos quedamos solo con las velas del último día de cotización disponible
    ultimo_dia = intradia["Datetime"].dt.date.max()
    intradia_hoy = intradia[intradia["Datetime"].dt.date == ultimo_dia].copy()
    return intradia_hoy[["Datetime", "Close"]]


def construir_dataframe_combinado() -> tuple[pd.DataFrame, pd.DataFrame]:
    diario = obtener_historico_diario()
    intradia_hoy = obtener_intradia_hoy()
    precio_intradia = float(intradia_hoy["Close"].iloc[-1])

    hoy = pd.Timestamp(datetime.now(TZ_CHILE).date())
    ultima_fecha_diaria = pd.Timestamp(diario["Date"].iloc[-1]).normalize()

    if ultima_fecha_diaria == hoy:
        # Reemplazamos el cierre provisional de hoy por el precio intradía
        diario.loc[diario.index[-1], "Close"] = precio_intradia
    else:
        # Aún no hay vela diaria para hoy (ej. corre antes del cierre) -> la agregamos
        nueva_fila = pd.DataFrame({"Date": [hoy], "Close": [precio_intradia]})
        diario = pd.concat([diario, nueva_fila], ignore_index=True)

    return diario, intradia_hoy


def main() -> None:
    print("[INFO]: Descargando datos y preparando animación...")
    datos_dolar, intradia_hoy = construir_dataframe_combinado()

    # Estadísticas del día (a partir de las velas intradía de hoy)
    apertura_dia = float(intradia_hoy["Close"].iloc[0])
    promedio_dia = float(intradia_hoy["Close"].mean())
    ultimo_dia = float(intradia_hoy["Close"].iloc[-1])
    marca_tiempo_intradia = intradia_hoy["Datetime"].iloc[-1]

    # === DataFrame acumulativo para la animación ===
    lista_marcos = []
    for i in range(len(datos_dolar)):
        sub_df = datos_dolar.iloc[: i + 1].copy()
        sub_df["Frame_Animacion"] = pd.Timestamp(datos_dolar["Date"].iloc[i]).strftime("%Y-%b-%d")
        lista_marcos.append(sub_df)

    df_animado = pd.concat(lista_marcos, ignore_index=True)

    max_precio = float(datos_dolar["Close"].max())
    min_precio = float(datos_dolar["Close"].min())
    prom_precio = float(datos_dolar["Close"].mean())
    ultimo_precio = float(datos_dolar["Close"].iloc[-1])

    fig = px.line(
        df_animado,
        x="Date",
        y="Close",
        animation_frame="Frame_Animacion",
        title=f"Evolución USD/CLP (YTD 2026) | ÚLTIMO VALOR: ${ultimo_precio:.2f} CLP",
        labels={"Close": "Precio (CLP)", "Date": "Fecha"},
        range_x=[datos_dolar["Date"].min(), datos_dolar["Date"].max()],
        range_y=[datos_dolar["Close"].min() - 15, datos_dolar["Close"].max() + 15],
    )

    marca_local = marca_tiempo_intradia.tz_localize("UTC").tz_convert(TZ_CHILE) \
        if marca_tiempo_intradia.tzinfo is None else marca_tiempo_intradia.tz_convert(TZ_CHILE)
    texto_actualizacion = marca_local.strftime("%d-%b-%Y %H:%M") + " (hora Chile)"

    fig.add_annotation(
        text=(
            f"<span style='font-size:14px; color:#38bdf8;'><b>ÚLTIMO PRECIO: ${ultimo_precio:.2f}</b></span><br>"
            f"---------------------------------<br>"
            f"<b>ESTADÍSTICAS DEL PERIODO</b><br>"
            f"Máximo: ${max_precio:.2f}<br>"
            f"Promedio: ${prom_precio:.2f}<br>"
            f"Mínimo: ${min_precio:.2f}<br>"
            f"---------------------------------<br>"
            f"<span style='font-size:10px; color:#94a3b8;'>Actualizado: {texto_actualizacion}</span>"
        ),
        xref="paper", yref="paper",
        x=0.02, y=0.95,
        xanchor="left", yanchor="top",
        showarrow=False,
        font=dict(size=12, color="#f8fafc", family="Arial"),
        bgcolor="rgba(15, 23, 42, 0.9)",
        bordercolor="rgba(56, 189, 248, 0.5)",
        borderwidth=1, borderpad=12,
    )

    # Cuadro nuevo: estadísticas del día (abajo a la derecha)
    fig.add_annotation(
        text=(
            f"<b>ESTADÍSTICAS DEL DÍA</b><br>"
            f"Apertura: ${apertura_dia:.2f}<br>"
            f"Promedio: ${promedio_dia:.2f}<br>"
            f"Último precio: ${ultimo_dia:.2f}"
        ),
        xref="paper", yref="paper",
        x=0.98, y=0.05,
        xanchor="right", yanchor="bottom",
        showarrow=False,
        font=dict(size=12, color="#f8fafc", family="Arial"),
        bgcolor="rgba(15, 23, 42, 0.9)",
        bordercolor="rgba(56, 189, 248, 0.5)",
        borderwidth=1, borderpad=12,
    )

    fig.add_hline(y=max_precio, line_dash="dot", line_color="#ef4444", opacity=0.4)
    fig.add_hline(y=min_precio, line_dash="dot", line_color="#22c55e", opacity=0.4)
    fig.add_hline(y=prom_precio, line_dash="dash", line_color="#94a3b8", opacity=0.4)

    fig.add_annotation(
        text="Herramienta analítica desarrollada para el Grupo Portfolio",
        xref="paper", yref="paper",
        x=0.5, y=-0.18,
        showarrow=False,
        font=dict(size=18, color="lightblue", family="Arial"),
    )

    fig.update_xaxes(rangeslider_visible=False)
    fig.update_layout(
        template="plotly_dark",
        margin=dict(b=90, t=60),
        plot_bgcolor="#0f172a",
        paper_bgcolor="#0f172a",
    )

    fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 30
    fig.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] = 10

    Path(ARCHIVO_SALIDA).write_text(fig.to_html(include_plotlyjs="cdn"), encoding="utf-8")
    print(f"[ÉXITO]: {ARCHIVO_SALIDA} generado. Último precio: ${ultimo_precio:.2f} ({texto_actualizacion})")

    # GitHub Actions define la variable de entorno "CI=true" automáticamente.
    # Solo abrimos el navegador cuando corremos el script en un computador local.
    if not os.environ.get("CI"):
        ruta_uri = Path(ARCHIVO_SALIDA).resolve().as_uri()
        webbrowser.open(ruta_uri)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR]: {exc}")
        sys.exit(1)