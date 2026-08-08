/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      screens: {
        // 手机 < 768px, PC >= 768px
        'xs': '480px',
      },
    },
  },
  plugins: [],
}
