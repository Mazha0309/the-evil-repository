import { createContext, useContext } from "react";

export type Locale = "zh-CN" | "en";

export interface LocaleValue {
  locale: Locale;
  isChinese: boolean;
  text: (chinese: string, english: string) => string;
  toggle: () => void;
}

export const LocaleContext = createContext<LocaleValue | null>(null);

export function useLocale(): LocaleValue {
  const value = useContext(LocaleContext);
  if (!value) throw new Error("useLocale must be used within LocaleProvider");
  return value;
}
