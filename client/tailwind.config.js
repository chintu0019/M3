/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        m3: {
          bg: "#0f0f13",
          surface: "#1a1a24",
          border: "#2a2a3a",
          text: "#e4e4ef",
          muted: "#8888a0",
          accent: "#6366f1",
          "accent-hover": "#818cf8",
        },
      },
    },
  },
  plugins: [],
};
