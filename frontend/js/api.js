/* ==========================================================================
   AI VERDANT — API client
   Change API_BASE_URL to point at your deployed backend, or leave it as
   localhost:5000 for local development.
   ========================================================================== */

var AIV = window.AIV || {};

AIV.API_BASE_URL = localStorage.getItem("aiv_api_base") || "https://ai-verdant.onrender.com";

AIV.setApiBase = (url) => {
  localStorage.setItem("aiv_api_base", url);
  AIV.API_BASE_URL = url;
};

AIV.getDeviceId = () => {
  const params = new URLSearchParams(window.location.search);
  return params.get("device") || localStorage.getItem("aiv_device_id") || "device-001";
};

AIV.setDeviceId = (id) => {
  localStorage.setItem("aiv_device_id", id);
};

async function request(path) {
  const res = await fetch(`${AIV.API_BASE_URL}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

AIV.api = {
  listDevices: () => request(`/api/devices`),
  latest: (deviceId) => request(`/api/devices/${deviceId}/latest`),
  history: (deviceId, hours = 24) => request(`/api/devices/${deviceId}/history?hours=${hours}`),
  recommendations: (deviceId) => request(`/api/devices/${deviceId}/recommendations`),
  strategy: (deviceId) => request(`/api/devices/${deviceId}/strategy`),
};

window.AIV = AIV;
