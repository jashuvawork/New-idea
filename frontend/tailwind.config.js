/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        nexus: {
          bg: '#0a0e17',
          panel: '#111827',
          'panel-elevated': '#151f31',
          border: '#1f2937',
          'border-light': '#374151',
          accent: '#06b6d4',
          green: '#10b981',
          red: '#ef4444',
          yellow: '#f59e0b',
          muted: '#9ca3af',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35)',
        'glow-accent': '0 0 20px rgba(6, 182, 212, 0.25)',
      },
      borderRadius: {
        xl: '0.75rem',
      },
    },
  },
  plugins: [],
};
