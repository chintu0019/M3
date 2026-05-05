/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      // Tokens mirror the CSS variables in src/index.css so existing
      // bg-m3-*, text-m3-* classes (mostly inside Settings) blend with the
      // canvas redesign.
      colors: {
        m3: {
          bg: "oklch(0.17 0.01 260)",
          surface: "oklch(0.21 0.012 260)",
          border: "oklch(0.32 0.012 260)",
          text: "oklch(0.96 0.005 260)",
          muted: "oklch(0.66 0.01 260)",
          accent: "oklch(0.78 0.14 220)",
          "accent-hover": "oklch(0.86 0.14 220)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
