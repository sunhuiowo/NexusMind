/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
        display: ['"Syne"', 'sans-serif'],
      },
      colors: {
        ink: {
          50:  '#f5f4f1',
          100: '#e8e6e0',
          200: '#ccc9c0',
          300: '#a8a49a',
          400: '#7c786e',
          500: '#5c5850',
          600: '#42403a',
          700: '#2e2c28',
          800: '#1e1d1a',
          900: '#111010',
        },
        accent: {
          DEFAULT: '#7C6FF7',
          light: '#a49af8',
          dark:  '#5a53d1',
        },
        success: '#22c55e',
        warning: '#f59e0b',
        danger:  '#ef4444',
      },
      animation: {
        'fade-in':     'fadeIn 0.18s ease-out',
        'slide-up':    'slideUp 0.22s ease-out',
        'slide-right': 'slideRight 0.2s ease-out',
        'pulse-soft':  'pulseSoft 2s ease-in-out infinite',
        'spin-slow':   'spin 3s linear infinite',
      },
      keyframes: {
        fadeIn:    { from: { opacity: '0' },                   to: { opacity: '1' } },
        slideUp:   { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideRight:{ from: { opacity: '0', transform: 'translateX(-8px)' }, to: { opacity: '1', transform: 'translateX(0)' } },
        pulseSoft: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.5' } },
      },
    },
  },
  plugins: [],
}
