// pages/Auth.tsx - Login/Register Page with AI Native Dark Theme
import { useState, useEffect, useCallback, memo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, Sparkles, ArrowRight, Eye, EyeOff, Shield, Zap, UserPlus, LogIn, LucideIcon } from 'lucide-react'
import { useAuthStore } from '../store'
import { cx } from '../utils'

// Form validation types
interface FormErrors {
  username?: string
  password?: string
  confirmPassword?: string
}

// Memoized input component for performance
const AuthInput = memo(function AuthInput({
  id,
  label,
  type,
  value,
  onChange,
  placeholder,
  icon: Icon,
  error,
  showPasswordToggle = false,
  showPassword,
  onTogglePassword,
  disabled,
}: {
  id: string
  label: string
  type: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  icon: LucideIcon
  error?: string
  showPasswordToggle?: boolean
  showPassword?: boolean
  onTogglePassword?: () => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-sm font-medium text-gray-300">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cx(
            'input-base pl-10 pr-10',
            error && 'border-danger focus:border-danger focus:ring-danger/20'
          )}
          disabled={disabled}
        />
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">
          <Icon size={18} />
        </div>
        {showPasswordToggle && (
          <button
            type="button"
            onClick={onTogglePassword}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        )}
      </div>
      {error && <p className="text-danger text-xs">{error}</p>}
    </div>
  )
})

type AuthMode = 'login' | 'register'

export default function Auth() {
  const navigate = useNavigate()
  const { isAuthenticated, login, register } = useAuthStore()

  const [mode, setMode] = useState<AuthMode>('register')
  const [isLoading, setIsLoading] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

  // Form fields
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  // Reset form when mode changes
  useEffect(() => {
    setUsername('')
    setPassword('')
    setConfirmPassword('')
    setErrors({})
  }, [mode])

  // Validate form
  const validateForm = useCallback((): boolean => {
    const newErrors: FormErrors = {}

    if (!username.trim()) {
      newErrors.username = '请输入用户名'
    } else if (username.trim().length < 2) {
      newErrors.username = '用户名至少需要2个字符'
    }

    if (!password) {
      newErrors.password = '请输入密码'
    } else if (password.length < 4) {
      newErrors.password = '密码至少需要4个字符'
    }

    if (mode === 'register') {
      if (password !== confirmPassword) {
        newErrors.confirmPassword = '两次输入的密码不一致'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }, [username, password, confirmPassword, mode])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrors({})

    if (!validateForm()) {
      return
    }

    setIsLoading(true)

    try {
      if (mode === 'register') {
        const result = await register(username, password, confirmPassword)
        if (result.success) {
          navigate('/', { replace: true })
        } else {
          setErrors({ username: result.error })
        }
      } else {
        const result = await login(username, password)
        if (result.success) {
          navigate('/', { replace: true })
        } else {
          setErrors({ username: result.error })
        }
      }
    } catch {
      setErrors({ username: '操作失败，请稍后重试' })
    } finally {
      setIsLoading(false)
    }
  }

  const toggleMode = () => {
    setMode(mode === 'login' ? 'register' : 'login')
  }

  return (
    <div className="min-h-screen bg-dark-bg flex items-center justify-center relative overflow-hidden">
      {/* Animated background gradient */}
      <div className="absolute inset-0 overflow-hidden">
        {/* Main gradient orbs */}
        <div className="absolute top-1/4 -left-1/4 w-[600px] h-[600px] bg-ai/8 rounded-full blur-[120px] animate-pulse-soft" />
        <div className="absolute bottom-1/4 -right-1/4 w-[500px] h-[500px] bg-ai-dark/10 rounded-full blur-[100px] animate-pulse-soft" style={{ animationDelay: '1s' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-accent/5 rounded-full blur-[150px]" />

        {/* Grid pattern overlay */}
        <div
          className="absolute inset-0 opacity-[0.015]"
          style={{
            backgroundImage: `linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px),
                             linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)`,
            backgroundSize: '60px 60px'
          }}
        />
      </div>

      {/* Main container */}
      <div className="relative z-10 w-full max-w-md px-6">
        {/* Logo and title */}
        <div className="text-center mb-10 animate-fade-in">
          {/* Logo icon */}
          <div className="inline-flex items-center justify-center w-20 h-20 mb-6 rounded-2xl bg-gradient-to-br from-ai to-ai-dark shadow-lg shadow-ai/25 relative">
            <Brain size={36} className="text-white" />
            <div className="absolute -top-1 -right-1 w-5 h-5 bg-ai-light rounded-full flex items-center justify-center">
              <Sparkles size={10} className="text-white" />
            </div>
          </div>

          <h1 className="text-3xl font-bold text-gray-100 mb-2 tracking-tight">
            Memory OS
          </h1>
          <p className="text-gray-500 text-sm">
            {mode === 'register' ? '创建你的私人 AI 知识助手' : '欢迎回来，继续你的知识之旅'}
          </p>
        </div>

        {/* Auth form */}
        <div className="card p-8 animate-slide-up" style={{ animationDelay: '0.1s' }}>
          {/* Mode toggle */}
          <div className="flex rounded-lg bg-dark-elevated p-1 mb-6">
            <button
              type="button"
              onClick={() => setMode('login')}
              className={cx(
                'flex-1 flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-medium transition-all',
                mode === 'login'
                  ? 'bg-ai text-white shadow-lg'
                  : 'text-gray-400 hover:text-gray-200'
              )}
            >
              <LogIn size={16} />
              登录
            </button>
            <button
              type="button"
              onClick={() => setMode('register')}
              className={cx(
                'flex-1 flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-medium transition-all',
                mode === 'register'
                  ? 'bg-ai text-white shadow-lg'
                  : 'text-gray-400 hover:text-gray-200'
              )}
            >
              <UserPlus size={16} />
              注册
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Username input */}
            <AuthInput
              id="username"
              label="用户名"
              type="text"
              value={username}
              onChange={setUsername}
              placeholder={mode === 'register' ? '创建用户名' : '输入用户名'}
              icon={Shield}
              error={errors.username}
              disabled={isLoading}
            />

            {/* Password input */}
            <AuthInput
              id="password"
              label="密码"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={setPassword}
              placeholder={mode === 'register' ? '创建密码' : '输入密码'}
              icon={Zap}
              error={errors.password}
              showPasswordToggle
              showPassword={showPassword}
              onTogglePassword={() => setShowPassword(!showPassword)}
              disabled={isLoading}
            />

            {/* Confirm password input (register only) */}
            {mode === 'register' && (
              <AuthInput
                id="confirmPassword"
                label="确认密码"
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={setConfirmPassword}
                placeholder="再次输入密码"
                icon={Zap}
                error={errors.confirmPassword}
                disabled={isLoading}
              />
            )}

            {/* Submit button */}
            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full py-3 text-base justify-center group relative overflow-hidden"
            >
              <span className="relative z-10 flex items-center gap-2">
                {isLoading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    {mode === 'register' ? '创建账户中...' : '登录中...'}
                  </>
                ) : (
                  <>
                    {mode === 'register' ? '创建账户' : '登录'}
                    <ArrowRight size={18} className="group-hover:translate-x-0.5 transition-transform" />
                  </>
                )}
              </span>
              {/* Button glow effect */}
              <div className="absolute inset-0 bg-gradient-to-r from-ai-light to-ai opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            </button>
          </form>

          {/* Footer */}
          <div className="mt-6 pt-6 border-t border-dark-border">
            <p className="text-xs text-gray-600 text-center">
              {mode === 'register' ? (
                <>
                  已有账户？
                  <button
                    type="button"
                    onClick={toggleMode}
                    className="text-ai hover:text-ai-light ml-1 font-medium"
                  >
                    立即登录
                  </button>
                </>
              ) : (
                <>
                  没有账户？
                  <button
                    type="button"
                    onClick={toggleMode}
                    className="text-ai hover:text-ai-light ml-1 font-medium"
                  >
                    立即注册
                  </button>
                </>
              )}
            </p>
          </div>
        </div>

        {/* Features highlight */}
        <div className="mt-8 flex justify-center gap-6 animate-slide-up" style={{ animationDelay: '0.2s' }}>
          {[
            { icon: Brain, label: 'AI 智能' },
            { icon: Shield, label: '本地存储' },
            { icon: Zap, label: '快速同步' }
          ].map((feature, idx) => (
            <div key={idx} className="flex items-center gap-2 text-gray-500 text-sm">
              <feature.icon size={14} className="text-ai" />
              <span>{feature.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Version info */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-gray-600 text-xs">
        v1.0.0
      </div>
    </div>
  )
}
