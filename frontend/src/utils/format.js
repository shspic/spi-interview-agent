export function formatDateTime(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatShortId(value, head = 8, tail = 4) {
  const text = value == null ? "" : String(value);
  if (text.length <= head + tail + 3) {
    return text || "--";
  }
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}
