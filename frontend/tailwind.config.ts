import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#14213d",
        accent: "#0f766e",
        highlight: "#c2410c",
        paper: "#f7f3eb",
        shell: "#f3f4f6"
      },
      boxShadow: {
        panel: "0 18px 40px rgba(20, 33, 61, 0.08)"
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "sans-serif"]
      }
    }
  },
  plugins: []
};

export default config;
