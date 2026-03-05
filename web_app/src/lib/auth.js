import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  sendPasswordResetEmail,
} from 'firebase/auth'
import { auth, googleProvider, hasFirebaseConfig } from './firebase'

function ensureFirebase() {
  if (!hasFirebaseConfig || !auth) {
    throw new Error('Firebase Auth is not configured. Fill .env from .env.example.')
  }
}

export function watchAuth(cb) {
  if (!hasFirebaseConfig || !auth) {
    cb(null)
    return () => {}
  }
  return onAuthStateChanged(auth, cb)
}

export async function loginWithEmail(email, password) {
  ensureFirebase()
  return signInWithEmailAndPassword(auth, email, password)
}

export async function loginWithGoogle() {
  ensureFirebase()
  if (!googleProvider) {
    throw new Error('Google auth provider unavailable.')
  }
  return signInWithPopup(auth, googleProvider)
}

export async function logout() {
  ensureFirebase()
  return signOut(auth)
}

export async function triggerPasswordReset(email) {
  ensureFirebase()
  if (!email) {
    throw new Error('Email is required to reset password.')
  }
  return sendPasswordResetEmail(auth, email)
}
