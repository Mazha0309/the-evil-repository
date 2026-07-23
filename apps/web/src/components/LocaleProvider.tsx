import { type ReactNode, useEffect, useMemo, useState } from "react";
import { LocaleContext, type Locale } from "../lib/i18n";

const STORAGE_KEY = "evil-repository.locale";

function initialLocale(): Locale {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "en" || stored === "zh-CN" ? stored : "zh-CN";
}

export default function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  const value = useMemo(
    () => ({
      locale,
      isChinese: locale === "zh-CN",
      text: (chinese: string, english: string) =>
        locale === "zh-CN" ? chinese : english,
      toggle: () =>
        setLocale((current) => {
          const next = current === "zh-CN" ? "en" : "zh-CN";
          window.localStorage.setItem(STORAGE_KEY, next);
          return next;
        }),
    }),
    [locale],
  );
  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}
