import { extendTheme } from '@chakra-ui/react'

const theme = extendTheme({
  config: {
    initialColorMode: 'dark',
    useSystemColorMode: false,
  },
  fonts: {
    heading: "'IBM Plex Sans', 'Segoe UI', sans-serif",
    body: "'IBM Plex Sans', 'Segoe UI', sans-serif",
  },
  styles: {
    global: {
      body: {
        bg: '#030303',
        color: '#f8f8f8',
      },
    },
  },
  colors: {
    brand: {
      black: '#030303',
      white: '#f8f8f8',
      card: '#0d0d0d',
      border: '#262626',
      yellow: '#f4d212',
      yellowHover: '#ffe452',
      purpleDeep: '#2a0a5e',
      red: '#d83a3a',
      redHover: '#f45353',
    },
  },
  components: {
    Button: {
      variants: {
        action: {
          bg: 'brand.yellow',
          color: '#101010',
          border: '1px solid',
          borderColor: '#e8c000',
          _hover: { bg: 'brand.yellowHover' },
        },
        danger: {
          bg: 'brand.red',
          color: 'white',
          border: '1px solid',
          borderColor: '#ff7777',
          _hover: { bg: 'brand.redHover' },
        },
        ghostline: {
          bg: 'transparent',
          border: '1px solid',
          borderColor: 'brand.border',
          color: 'brand.white',
          _hover: { bg: '#121212' },
        },
      },
      defaultProps: {
        size: 'sm',
      },
    },
    Card: {
      baseStyle: {
        container: {
          bg: 'brand.card',
          border: '1px solid',
          borderColor: 'brand.border',
          borderRadius: '8px',
          boxShadow: '0 8px 18px rgba(0,0,0,0.35)',
        },
      },
    },
  },
})

export default theme
