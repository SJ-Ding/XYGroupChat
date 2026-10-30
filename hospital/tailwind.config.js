/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        med: { 50: '#EFF6FF', 100: '#DBEAFE', 200: '#BFDBFE', 400: '#60A5FA', 500: '#3B82F6', 600: '#2563EB', 700: '#1D4ED8' },
        sky: { light: '#E0F2FE', DEFAULT: '#0EA5E9' },
      },
      fontFamily: { sans: ['"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'] },
      boxShadow: { card: '0 2px 12px -2px rgba(37, 99, 235, 0.10)' },
    },
  },
  plugins: [],
};
