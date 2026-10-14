import React, { CSSProperties, useState, useEffect } from "react";
import { useTheme } from "@/lib/theme-provider";
import { cn } from "@/lib/utils";

interface GradientBackgroundProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  withNoise?: boolean;
  // Debug props
  noiseFrequency?: number;
  noiseOctaves?: number;
  noiseOpacity?: number;
}

/**
 * A component that provides a consistent gradient background from dark to light
 * with proper transparency for child components to blend with.
 */
export function GradientBackground({
  children,
  className,
  withNoise = true,
  noiseFrequency = 1.2,
  noiseOctaves = 4,
  noiseOpacity,
  ...props
}: GradientBackgroundProps) {
  const { resolvedTheme } = useTheme();
  const [key, setKey] = useState(Date.now());

  // Force re-render when noise parameters change
  useEffect(() => {
    setKey(Date.now());
  }, [noiseFrequency, noiseOctaves, noiseOpacity]);

  const getGradientClass = () => {
    if (resolvedTheme === 'dark') {
      return "from-black via-black to-background-alpha-10";
    } else {
      return "from-background-alpha-40 via-background-alpha-40 to-white";
    }
  };

  const gradientClass = `bg-gradient-to-b ${getGradientClass()}`;

  // CSS for the noise texture overlay
  const noiseStyle: CSSProperties = withNoise ? {
    position: 'relative',
  } : {};

  const defaultOpacity = resolvedTheme === 'dark' ? 0.05 : 0.03;
  const finalOpacity = noiseOpacity !== undefined ? noiseOpacity : defaultOpacity;

  const noiseAfterStyle: CSSProperties = withNoise ? {
    content: '""',
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    opacity: finalOpacity,
    backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='${noiseFrequency}' numOctaves='${noiseOctaves}' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`,
    pointerEvents: 'none',
    zIndex: 0,
  } : {};

  return (
    <div
      className={cn(gradientClass, className)}
      style={noiseStyle}
      {...props}
    >
      {withNoise && <div key={key} style={noiseAfterStyle} aria-hidden="true" />}
      <div style={{ position: 'relative', zIndex: 1 }}>
        {children}
      </div>
    </div>
  );
}

/**
 * A component that provides a semi-transparent card with backdrop blur
 * to be used on top of the gradient background.
 */
export function GradientCard({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  const { resolvedTheme } = useTheme();

  const bgClass = resolvedTheme === 'dark'
    ? "bg-background-alpha-40"
    : "white";

  return (
    <div
      className={cn(
        `${bgClass} backdrop-blur-md`,
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
