import { useCallback, useEffect, useState } from "react";

export function currentLocation() {
  return `${window.location.pathname}${window.location.search}`;
}

export function useLocationPath() {
  const [location, setLocation] = useState(currentLocation);

  useEffect(() => {
    const handlePopState = () => setLocation(currentLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((next, { replace = false } = {}) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", next);
    setLocation(currentLocation());
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);

  return { location, pathname: window.location.pathname, navigate };
}
