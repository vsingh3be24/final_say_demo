import axios, { AxiosError } from 'axios'

// Single axios instance. Base URL is the same-origin /api path; in dev the Vite
// proxy forwards it to the FastAPI backend at 127.0.0.1:8000.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
})

const TOKEN_KEY = 'finalsay_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

// Attach the bearer token to every request when present.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Turn backend error payloads into readable messages for the UI.
export function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail
    const status = err.response?.status
    if (status === 409) {
      return 'That email is already registered. Log in or use a different email.'
    }
    if (status === 503 || status === 502 || status === 504) {
      return 'FinalSay is temporarily unavailable. Please try again shortly.'
    }
    if (status !== undefined && status >= 500) {
      return 'FinalSay could not complete that request. Please try again shortly.'
    }
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      return `Please check your information: ${detail
        .map((d: { msg?: string }) => d.msg ?? 'invalid value')
        .join('; ')}`
    }
    if (err.code === 'ERR_NETWORK' || !err.response) {
      return 'Cannot reach FinalSay. Check that the app is running and try again.'
    }
    if (status === 401) return 'The email or password is incorrect.'
    if (status === 422) return 'Please check the information and try again.'
    if (status === 429) return 'Too many attempts. Please wait and try again.'
    if (status && status >= 400) return 'FinalSay could not accept that request.'
  }
  return 'Something went wrong. Please try again.'
}

