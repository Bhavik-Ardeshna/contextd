/**
 * KPIOrb - Animated metric display with glowing orb effect
 * 
 * Shows a metric value with:
 * - Animated count-up on load
 * - Pulsing glow for critical values
 * - Trend indicator
 * - Click to drill down
 */
import { useState, useEffect, useRef } from 'react';
import { TrendingUp, TrendingDown, Minus, ChevronRight } from 'lucide-react';

interface KPIProps {
  label: string;
  value: number;
  trend?: number; // Percentage change
  trendLabel?: string;
  severity?: 'normal' | 'warning' | 'critical';
  onClick?: () => void;
  icon?: React.ReactNode;
  suffix?: string;
  prefix?: string;
  animate?: boolean;
  delay?: number; // Animation delay in ms
}

export function KPIOrb({
  label,
  value,
  trend,
  trendLabel,
  severity = 'normal',
  onClick,
  icon,
  suffix,
  prefix,
  animate = true,
  delay = 0,
}: KPIProps) {
  const [displayValue, setDisplayValue] = useState(animate ? 0 : value);
  const [isVisible, setIsVisible] = useState(!animate);
  const animationRef = useRef<number | undefined>(undefined);

  // Animate count-up
  useEffect(() => {
    if (!animate) {
      setDisplayValue(value);
      return;
    }

    // Delay before starting animation
    const delayTimer = setTimeout(() => {
      setIsVisible(true);
      
      const startTime = Date.now();
      const duration = 1000; // 1 second animation

      const animateValue = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // Easing function (ease-out cubic)
        const eased = 1 - Math.pow(1 - progress, 3);
        
        setDisplayValue(Math.round(eased * value));

        if (progress < 1) {
          animationRef.current = requestAnimationFrame(animateValue);
        }
      };

      animationRef.current = requestAnimationFrame(animateValue);
    }, delay);

    return () => {
      clearTimeout(delayTimer);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [value, animate, delay]);

  const getSeverityClasses = () => {
    switch (severity) {
      case 'critical':
        return {
          glow: 'hover:glow-critical',
          border: 'border-foreground/30 hover:border-foreground/50',
          indicator: 'bg-foreground',
          text: 'text-foreground',
        };
      case 'warning':
        return {
          glow: 'hover:glow-warning',
          border: 'border-muted-foreground/30 hover:border-muted-foreground/50',
          indicator: 'bg-muted-foreground',
          text: 'text-muted-foreground',
        };
      default:
        return {
          glow: 'hover:glow-blue',
          border: 'border-primary/30 hover:border-primary/50',
          indicator: 'bg-primary',
          text: 'text-primary',
        };
    }
  };

  const classes = getSeverityClasses();

  const getTrendIcon = () => {
    if (trend === undefined || trend === null) return null;
    if (trend > 0) return <TrendingUp className="w-3 h-3" />;
    if (trend < 0) return <TrendingDown className="w-3 h-3" />;
    return <Minus className="w-3 h-3" />;
  };

  const getTrendColor = () => {
    if (trend === undefined || trend === null) return 'text-muted-foreground';
    // For most metrics, up is bad (more issues)
    if (trend > 0) return 'text-foreground';
    if (trend < 0) return 'text-primary';
    return 'text-muted-foreground';
  };

  const formatTrend = () => {
    if (trend === undefined || trend === null) return null;
    const sign = trend > 0 ? '+' : '';
    return `${sign}${trend}%`;
  };

  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`
        group relative p-5 rounded-2xl glass-card
        border transition-all duration-300
        ${classes.border} ${classes.glow}
        ${onClick ? 'cursor-pointer hover-lift' : 'cursor-default'}
        ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}
      `}
      style={{
        transitionDelay: isVisible ? '0ms' : `${delay}ms`,
      }}
    >
      {/* Severity indicator dot */}
      {severity !== 'normal' && (
        <div className={`
          absolute top-3 right-3 w-2 h-2 rounded-full ${classes.indicator}
          animate-pulse
        `} />
      )}

      {/* Icon */}
      {icon && (
        <div className="mb-3 text-muted-foreground group-hover:text-foreground/60 transition-colors">
          {icon}
        </div>
      )}

      {/* Value */}
      <div className="text-3xl font-semibold font-display text-foreground mb-1">
        {prefix}
        <span className="font-mono-data">{displayValue.toLocaleString()}</span>
        {suffix}
      </div>

      {/* Label */}
      <div className="text-sm text-muted-foreground mb-2">
        {label}
      </div>

      {/* Trend */}
      {trend !== undefined && (
        <div className={`flex items-center gap-1 text-xs ${getTrendColor()}`}>
          {getTrendIcon()}
          <span className="font-mono-data">{formatTrend()}</span>
          {trendLabel && (
            <span className="text-muted-foreground/70 ml-1">{trendLabel}</span>
          )}
        </div>
      )}

      {/* Click indicator */}
      {onClick && (
        <div className="absolute bottom-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        </div>
      )}
    </button>
  );
}

// Mini sparkline component for use inside KPI orbs
export function Sparkline({ 
  data, 
  height = 24, 
  color = '#a855f7' 
}: { 
  data: number[]; 
  height?: number;
  color?: string;
}) {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * 100;
    const y = height - ((value - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg 
      viewBox={`0 0 100 ${height}`} 
      className="w-full" 
      style={{ height }}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="sparkline-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      
      {/* Area fill */}
      <polygon
        points={`0,${height} ${points} 100,${height}`}
        fill="url(#sparkline-gradient)"
      />
      
      {/* Line */}
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      
      {/* End point */}
      <circle
        cx="100"
        cy={height - ((data[data.length - 1] - min) / range) * height}
        r="2"
        fill={color}
      />
    </svg>
  );
}

export default KPIOrb;
