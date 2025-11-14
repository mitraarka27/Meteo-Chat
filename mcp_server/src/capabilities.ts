/**
 * capabilities.ts
 * ----------------
 * Dynamic discovery + daily-cached capability index for Open-Meteo.
 *
 * Exposes:
 *  - describeCapabilities(): Promise<Capabilities>
 *
 * We keep the original structure but extend the seed descriptor so that
 * ALL canonical targets from resolve_variable_aliases() in app.py are
 * explicitly represented here as CapabilityVariable entries.
 */

import { fetch } from "undici";

export type CapabilityVariable = {
  id: string;           // canonical parameter name, e.g., "temperature_2m"
  label: string;        // human-readable label
  unit?: string;        // canonical unit
  time_modes: ("historical" | "current" | "forecast" | "climate")[];
  aliases?: string[];   // fuzzy matches
};

export type Capabilities = {
  provider: "open-meteo";
  last_updated: string;
  variables: CapabilityVariable[];
};

let memCache: { value: Capabilities; expires: number } | null = null;
const DAY = 24 * 60 * 60 * 1000;

/** Seed descriptor: extended but still conservative. */
const seed: Capabilities = {
  provider: "open-meteo",
  last_updated: new Date().toISOString(),
  variables: [
    // ------------------ Temperature & humidity ------------------
    {
      id: "temperature_2m",
      label: "2 m air temperature",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["temperature", "air temperature", "temp", "t2m"]
    },
    {
      id: "apparent_temperature",
      label: "Apparent temperature (2 m)",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["apparent temperature", "feels like", "feels_like"]
    },
    {
      id: "dew_point_2m",
      label: "Dew point (2 m)",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["dewpoint", "dew_point", "dew point temperature"]
    },
    {
      id: "relative_humidity_2m",
      label: "2 m relative humidity",
      unit: "%",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["humidity", "relative humidity", "rh"]
    },

    // ------------------ Wind ------------------
    {
      id: "wind_speed_10m",
      label: "10 m wind speed",
      unit: "m/s",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["wind", "winds", "wind speed", "wind_speed_10m", "windspeed_10m"]
    },
    {
      id: "wind_direction_10m",
      label: "10 m wind direction",
      unit: "°",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["wind_dir", "wind direction", "wind_direction_10m"]
    },
    {
      id: "wind_gusts_10m",
      label: "10 m wind gusts",
      unit: "m/s",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["wind gust", "wind gusts", "gust", "gusts", "wind_gusts_10m", "windgusts_10m"]
    },

    // ------------------ Precipitation / hydrology ------------------
    {
      id: "precipitation",
      label: "Precipitation",
      unit: "mm",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["precip", "precipitation", "rain+snow"]
    },
    {
      id: "rain",
      label: "Rain",
      unit: "mm",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["rain"]
    },
    {
      id: "snowfall",
      label: "Snowfall",
      unit: "cm",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["snow", "snowfall"]
    },
    {
      id: "snow_depth",
      label: "Snow depth",
      unit: "cm",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["snow depth"]
    },

    // ------------------ Cloud / radiation ------------------
    {
      id: "cloud_cover",
      label: "Total cloud cover",
      unit: "%",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["cloud", "clouds", "cloud cover", "cloud_cover", "cloudcover"]
    },
    {
      id: "shortwave_radiation",
      label: "Shortwave solar radiation (GHI)",
      unit: "W/m²",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["shortwave_radiation", "shortwave radiation", "ghi"]
    },
    {
      id: "direct_radiation",
      label: "Direct solar radiation",
      unit: "W/m²",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["direct_radiation", "direct radiation"]
    },
    {
      id: "diffuse_radiation",
      label: "Diffuse solar radiation",
      unit: "W/m²",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["diffuse_radiation", "diffuse radiation"]
    },
    {
      id: "et0_fao_evapotranspiration",
      label: "Reference evapotranspiration (ET0, FAO)",
      unit: "mm",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["et0", "evapotranspiration", "reference evapotranspiration"]
    },

    // ------------------ Pressure ------------------
    {
      id: "pressure_msl",
      label: "Mean sea level pressure",
      unit: "hPa",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["mslp", "sea level pressure", "mean sea level pressure"]
    },
    {
      id: "surface_pressure",
      label: "Surface pressure",
      unit: "hPa",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["surface_pressure", "surface pressure"]
    },

    // ------------------ Soil temperature ------------------
    {
      id: "soil_temperature_0cm",
      label: "Soil temperature (0 cm)",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: [
        "soil_surface_temperature",
        "soil_temperature_surface",
        "soil_temp_surface",
        "soil_temperature_0cm",
        "soil_temp_0cm"
      ]
    },
    {
      id: "soil_temperature_6cm",
      label: "Soil temperature (6 cm)",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_temperature_6cm", "soil_temp_6cm"]
    },
    {
      id: "soil_temperature_18cm",
      label: "Soil temperature (18 cm)",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_temperature_18cm", "soil_temp_18cm"]
    },
    {
      id: "soil_temperature_54cm",
      label: "Soil temperature (54 cm)",
      unit: "°C",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_temperature_54cm", "soil_temp_54cm"]
    },

    // ------------------ Soil moisture ------------------
    {
      id: "soil_moisture_0_to_1cm",
      label: "Soil moisture (0–1 cm)",
      unit: "m³/m³",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_moisture_0_1cm", "soil_moisture_0_1"]
    },
    {
      id: "soil_moisture_1_to_3cm",
      label: "Soil moisture (1–3 cm)",
      unit: "m³/m³",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_moisture_1_3cm"]
    },
    {
      id: "soil_moisture_3_to_9cm",
      label: "Soil moisture (3–9 cm)",
      unit: "m³/m³",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_moisture_3_9cm"]
    },
    {
      id: "soil_moisture_9_to_27cm",
      label: "Soil moisture (9–27 cm)",
      unit: "m³/m³",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_moisture_9_27cm"]
    },
    {
      id: "soil_moisture_27_to_81cm",
      label: "Soil moisture (27–81 cm)",
      unit: "m³/m³",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["soil_moisture_27_81cm"]
    },

    // ------------------ Visibility & UV ------------------
    {
      id: "visibility",
      label: "Horizontal visibility",
      unit: "m",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["visibility"]
    },
    {
      id: "uv_index",
      label: "UV index",
      unit: "",
      time_modes: ["historical", "current", "forecast"],
      aliases: ["uv_index", "uv index"]
    },

    // ------------------ Daily aggregates (planned; UI may add later) ------------------
    {
      id: "temperature_2m_max",
      label: "Daily maximum 2 m temperature",
      unit: "°C",
      time_modes: ["historical", "forecast"],
      aliases: ["tmax", "temperature_max", "max temperature"]
    },
    {
      id: "temperature_2m_min",
      label: "Daily minimum 2 m temperature",
      unit: "°C",
      time_modes: ["historical", "forecast"],
      aliases: ["tmin", "temperature_min", "min temperature"]
    }

    // Note: sunrise / sunset are DAILY-only variables. They are *not*
    // wired into executor.ts (which only calls hourly endpoints), so we
    // intentionally leave them out of capabilities for now. If you want
    // them, executor needs a small “daily” path.
  ]
};

async function refreshFromOpenMeteo(): Promise<Capabilities> {
  // We keep the original “ping a harmless forecast” strategy and just
  // refresh the timestamp. If the ping fails, fall back to seed.
  try {
    const url =
      "https://api.open-meteo.com/v1/forecast" +
      "?latitude=0&longitude=0&hourly=temperature_2m,relative_humidity_2m," +
      "wind_speed_10m,cloud_cover,precipitation&timezone=auto";
    const r = await fetch(url);
    if (!r.ok) throw new Error("open-meteo-metadata-failed");
    return { ...seed, last_updated: new Date().toISOString() };
  } catch {
    return seed;
  }
}

export async function describeCapabilities(): Promise<Capabilities> {
  if (memCache && Date.now() < memCache.expires) return memCache.value;
  const fresh = await refreshFromOpenMeteo();
  memCache = { value: fresh, expires: Date.now() + DAY };
  return fresh;
}