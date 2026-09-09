/* ==========================================================================
   AI VERDANT — Shared UI helpers
   ========================================================================== */

var AIV = window.AIV || {};

/* ==========================================================================
   SENSOR METADATA
   ========================================================================== */

AIV.SENSOR_META = {
  temperature_c: {
    label: "Temperature",
    unit: "°C",
    icon: "🌡",
    range: [18, 30],
    color: "#ff3df0"
  },

  humidity_pct: {
    label: "Humidity",
    unit: "%",
    icon: "💧",
    range: [40, 70],
    color: "#39e6ff"
  },

  soil_moisture_pct: {
    label: "Soil Moisture",
    unit: "%",
    icon: "🌱",
    range: [35, 65],
    color: "#39ff88"
  },

  ph: {
    label: "Soil pH",
    unit: "",
    icon: "⚗",
    range: [6.0, 7.0],
    color: "#ffb84d"
  },

  water_level_cm: {
    label: "Ultrasonic Distance",
    unit: "cm",
    icon: "📡",
    range: [5, 100],
    color: "#39e6ff"
  },

  motion_detected: {
    label: "Motion",
    unit: "",
    icon: "🎯",
    range: null,
    color: "#ff3df0"
  }
};


/* ==========================================================================
   NAVIGATION
   ========================================================================== */

AIV.NAV_ITEMS = [
  {
    href: "index.html",
    label: "Dashboard",
    icon: "▣"
  },

  {
    href: "sensors.html",
    label: "Sensor Details",
    icon: "◈"
  },

  {
    href: "trends.html",
    label: "Trends & History",
    icon: "∿"
  },

  {
    href: "strategy.html",
    label: "Optimal Strategy",
    icon: "✦"
  },

  {
    href: "settings.html",
    label: "Settings",
    icon: "⚙"
  }
];


/* ==========================================================================
   SHARED APPLICATION SHELL
   ========================================================================== */

AIV.renderShell = async (activeHref) => {

  const page =
    window.location.pathname.split("/").pop() || "index.html";

  const navHtml = AIV.NAV_ITEMS
    .map((item) => {

      const active =
        page === item.href ? "active" : "";

      return `
        <a
          href="${item.href}${window.location.search}"
          class="${active}"
        >
          <span class="icon">${item.icon}</span>
          ${item.label}
        </a>
      `;
    })
    .join("");


  /* ------------------------------------------------------------------------
     Load available devices
     ------------------------------------------------------------------------ */

  let devices = [];

  try {

    devices = await AIV.api.listDevices();

  } catch (error) {

    /*
      Backend may not be reachable.
      The rest of the page should still load.
    */

    devices = [];
  }


  /* ------------------------------------------------------------------------
     Current device
     ------------------------------------------------------------------------ */

  const currentDevice =
    AIV.getDeviceId();


  /* ------------------------------------------------------------------------
     Device dropdown
     ------------------------------------------------------------------------ */

  const deviceOptions = devices.length

    ? devices
        .map((device) => {

          const selected =
            device.device_id === currentDevice
              ? "selected"
              : "";

          return `
            <option
              value="${device.device_id}"
              ${selected}
            >
              ${device.name || device.device_id}
            </option>
          `;
        })
        .join("")

    : `
        <option value="${currentDevice}">
          ${currentDevice}
        </option>
      `;


  /* ------------------------------------------------------------------------
     Sidebar
     ------------------------------------------------------------------------ */

  const sidebar =
    document.getElementById("aiv-sidebar");


  if (!sidebar) {
    return;
  }


  sidebar.innerHTML = `

    <div class="brand">

      <div class="brand-mark">
        AV
      </div>

      <div>

        <div class="brand-name">
          AI Verdant
        </div>

        <div class="brand-sub">
          Live farm intelligence
        </div>

      </div>

    </div>


    <nav class="nav">
      ${navHtml}
    </nav>


    <div class="device-picker">

      <label for="aiv-device-select">
        Active device
      </label>

      <select id="aiv-device-select">
        ${deviceOptions}
      </select>

    </div>
  `;


  /* ------------------------------------------------------------------------
     Device switching
     ------------------------------------------------------------------------ */

  const deviceSelect =
    document.getElementById("aiv-device-select");


  if (deviceSelect) {

    deviceSelect.addEventListener(
      "change",
      (event) => {

        const deviceId =
          event.target.value;

        AIV.setDeviceId(deviceId);

        const url =
          new URL(window.location.href);

        url.searchParams.set(
          "device",
          deviceId
        );

        window.location.href =
          url.toString();
      }
    );
  }

};


/* ==========================================================================
   SCORE COLOR
   ========================================================================== */

AIV.scoreColor = (score) => {

  if (
    score === null ||
    score === undefined
  ) {
    return "#7fa691";
  }

  if (score >= 80) {
    return "#39ff88";
  }

  if (score >= 55) {
    return "#ffb84d";
  }

  return "#ff3df0";
};


/* ==========================================================================
   SEVERITY BADGES
   ========================================================================== */

AIV.severityBadge = (severity) => {

  const map = {

    urgent: {
      cls: "badge-urgent",
      label: "Urgent"
    },

    action: {
      cls: "badge-action",
      label: "Action"
    },

    watch: {
      cls: "badge-watch",
      label: "Watch"
    },

    info: {
      cls: "badge-info",
      label: "Info"
    }

  };


  const selected =
    map[severity] || map.info;


  return `
    <span class="badge ${selected.cls}">
      <span class="dot"></span>
      ${selected.label}
    </span>
  `;
};


/* ==========================================================================
   SCORE RING
   ========================================================================== */

AIV.renderScoreRing = (
  elementId,
  score
) => {

  const size = 150;

  const stroke = 12;

  const radius =
    (size - stroke) / 2;

  const circumference =
    2 * Math.PI * radius;


  const percentage =
    score === null ||
    score === undefined

      ? 0

      : Math.max(
          0,
          Math.min(100, score)
        );


  const offset =
    circumference -
    (percentage / 100) *
      circumference;


  const color =
    AIV.scoreColor(score);


  const element =
    document.getElementById(elementId);


  if (!element) {
    return;
  }


  element.innerHTML = `

    <svg
      width="${size}"
      height="${size}"
      viewBox="0 0 ${size} ${size}"
    >

      <circle
        cx="${size / 2}"
        cy="${size / 2}"
        r="${radius}"
        stroke="#16261f"
        stroke-width="${stroke}"
        fill="none"
      />

      <circle
        cx="${size / 2}"
        cy="${size / 2}"
        r="${radius}"
        stroke="${color}"
        stroke-width="${stroke}"
        fill="none"
        stroke-linecap="round"
        stroke-dasharray="${circumference}"
        stroke-dashoffset="${offset}"
        style="
          filter: drop-shadow(0 0 8px ${color}88);
          transition: stroke-dashoffset .6s ease;
        "
      />

    </svg>


    <div class="score-ring-value">

      <div
        class="num"
        style="color:${color}"
      >
        ${
          score === null ||
          score === undefined
            ? "—"
            : score
        }
      </div>

      <div class="lbl">
        out of 100
      </div>

    </div>
  `;
};


/* ==========================================================================
   DATE / TIME FORMATTER
   ========================================================================== */

AIV.formatTime = (iso) => {

  try {

    return new Date(iso).toLocaleString(
      undefined,
      {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      }
    );

  } catch {

    return iso;

  }
};


/* ==========================================================================
   EMPTY STATE
   ========================================================================== */

AIV.emptyState = (message) => {

  return `
    <div class="empty-state">
      ${message}
    </div>
  `;

};


/* ==========================================================================
   SERVICE WORKER
   ========================================================================== */

if ("serviceWorker" in navigator) {

  window.addEventListener(
    "load",
    () => {

      navigator.serviceWorker
        .register("sw.js")
        .catch(() => {

          /*
            Service worker failure is non-fatal.
            The application can still operate normally.
          */

        });

    }
  );

}


/* ==========================================================================
   EXPOSE AI VERDANT OBJECT
   ========================================================================== */

window.AIV = AIV;