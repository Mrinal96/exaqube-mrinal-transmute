/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        /* ── Surface layers (dark → light) ── */
        surface: {
          DEFAULT: '#0c0e12',
          base: '#0e1014',
          raised: '#101216',
          overlay: '#111318',
          card: '#14161c',
          elevated: '#171920',
          input: '#191b21',
          hover: '#1b1d23',
          active: '#202229',
          muted: '#22252d',
        },
        /* ── Border scale ── */
        border: {
          DEFAULT: '#24262d',
          subtle: '#202229',
          muted: '#292b33',
          strong: '#30323b',
          prominent: '#343741',
          focus: '#9988f6',
        },
        /* ── Text scale ── */
        text: {
          DEFAULT: '#e8e9ed',
          primary: '#e2e3e8',
          secondary: '#b1b3bb',
          tertiary: '#8b8f9a',
          muted: '#777c87',
          faint: '#656a75',
          disabled: '#535660',
        },
        /* ── Accent: Purple (primary) ── */
        accent: {
          DEFAULT: '#8470e9',
          light: '#a491ff',
          lighter: '#c8baff',
          subtle: '#ae9eff',
          dim: '#8270e6',
          dark: '#7865d7',
          bg: '#24212f',
          'bg-hover': '#302b3b',
          border: '#39334c',
          'border-strong': '#494064',
          text: '#d3caff',
        },
        /* ── Status: Success / Teal ── */
        success: {
          DEFAULT: '#54bd91',
          light: '#6ebd9c',
          dim: '#65b99c',
          dot: '#62bd99',
          bg: '#315d4f',
          text: '#75bb9e',
        },
        /* ── Status: Warning / Orange ── */
        warning: {
          DEFAULT: '#e78955',
          light: '#e79a65',
          dim: '#d29069',
          bg: '#51402c',
          text: '#dbb686',
        },
        /* ── Status: Error / Red ── */
        error: {
          DEFAULT: '#e0807e',
          light: '#e0847d',
          bg: '#71413d',
          text: '#e0807e',
        },
        /* ── Status: Info / Blue ── */
        info: {
          DEFAULT: '#6ea5ed',
        },
        /* ── Status: Cyan ── */
        cyan: {
          DEFAULT: '#49c5c5',
        },
        /* ── Format-specific accent colours ── */
        'fmt-pptx': '#e78955',
        'fmt-xlsx': '#54bd91',
        'fmt-docx': '#6ea5ed',
        'fmt-mmd': '#b39cf2',
        'fmt-html': '#49c5c5',
      },
      fontFamily: {
        sans: ['DM Sans', 'system-ui', 'sans-serif'],
        mono: ['DM Mono', 'ui-monospace', 'monospace'],
        display: ['Manrope', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['8px', { lineHeight: '1.4' }],
        xs: ['9px', { lineHeight: '1.5' }],
        sm: ['10px', { lineHeight: '1.5' }],
        base: ['11px', { lineHeight: '1.55' }],
        md: ['12px', { lineHeight: '1.6' }],
        lg: ['13px', { lineHeight: '1.55' }],
        xl: ['14px', { lineHeight: '1.45' }],
        '2xl': ['17px', { lineHeight: '1.35' }],
        '3xl': ['22px', { lineHeight: '1.25' }],
        '4xl': ['28px', { lineHeight: '1.18' }],
        '5xl': ['31px', { lineHeight: '1.17' }],
      },
      spacing: {
        4.5: '18px',
        13: '52px',
        15: '60px',
        18: '72px',
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '5px',
        md: '6px',
        lg: '7px',
        xl: '8px',
        '2xl': '9px',
        '3xl': '10px',
        '4xl': '13px',
      },
      boxShadow: {
        'card': '0 8px 24px rgba(0, 0, 0, 0.25)',
        'elevated': '0 8px 28px rgba(0, 0, 0, 0.2)',
        'overlay': '0 8px 28px rgba(0, 0, 0, 0.45)',
        'glow-accent': '0 4px 18px rgba(130, 112, 230, 0.2)',
        'glow-success': '0 4px 14px rgba(84, 189, 145, 0.2)',
        'glow-warning': '0 4px 14px rgba(231, 137, 85, 0.2)',
        'node': '0 8px 24px rgba(0, 0, 0, 0.25)',
        'node-selected': '0 0 0 2px color-mix(in srgb, var(--node-accent, #8470e9), transparent 78%), 0 8px 24px rgba(0, 0, 0, 0.3)',
        'toast': '0 8px 28px rgba(0, 0, 0, 0.45)',
        'dropdown': '0 12px 36px rgba(0, 0, 0, 0.5)',
      },
      animation: {
        'spin-slow': 'spin 1.1s linear infinite',
        'fade-in': 'fadeIn 0.16s ease-out',
        'fade-out': 'fadeOut 0.12s ease-in',
        'slide-up': 'slideUp 0.2s ease-out',
        'slide-down': 'slideDown 0.2s ease-out',
        'slide-right': 'slideRight 0.2s ease-out',
        'scale-in': 'scaleIn 0.15s ease-out',
        'pulse-dot': 'pulseDot 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        fadeOut: {
          from: { opacity: '1' },
          to: { opacity: '0' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          from: { opacity: '0', transform: 'translateY(-8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideRight: {
          from: { opacity: '0', transform: 'translateX(-8px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        scaleIn: {
          from: { opacity: '0', transform: 'scale(0.95)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        pulseDot: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
      },
      transitionDuration: {
        DEFAULT: '160ms',
      },
      transitionTimingFunction: {
        DEFAULT: 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
}
