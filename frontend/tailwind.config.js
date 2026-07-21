/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        accent:         '#6366f1',
        'accent-hover': '#4f46e5',
        'accent-active':'#4338ca',
        ink:            '#0f172a',
        primary:        '#0f172a',
        light:          '#fafafa',
        'indigo-50':    '#eef2ff',
        'indigo-100':   '#e0e7ff',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        xs:     '0 1px 2px rgba(15,23,42,.04)',
        sm:     '0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)',
        accent: '0 4px 14px rgba(99,102,241,.25)',
      },
    },
  },
  plugins: [],
}
