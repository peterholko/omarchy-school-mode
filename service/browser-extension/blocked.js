"use strict";
let target = null;
try {
  const url = new URL(decodeURIComponent(location.hash.slice(1)));
  if (["http:", "https:"].includes(url.protocol)) target = url;
} catch (_) {}
document.getElementById("domain").textContent = target ? target.hostname : "This website is taking a break.";
const retry = document.getElementById("retry");
retry.disabled = !target;
retry.addEventListener("click", () => { if (target) location.replace(target.href); });
