const evt = new EventSource("/logs");
evt.onmessage = e => {
  const logsEl = document.getElementById("logs");
  const line   = e.data;
  let cls      = "text-light";
  if (line.includes("DEBUG"))   cls = "text-secondary";
  if (line.includes("INFO"))    cls = "text-info";
  if (line.includes("WARNING")) cls = "text-warning";
  if (line.includes("ERROR"))   cls = "text-danger";

  const span = document.createElement("span");
  span.textContent = line + "\n";
  span.className   = cls;

  // insert new line at the top
  logsEl.prepend(span);

  // keep view pinned to the top (newest entry)
  logsEl.scrollTop = 0;
};
