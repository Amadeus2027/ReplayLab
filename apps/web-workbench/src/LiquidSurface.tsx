import type { ReactNode } from "react";
import LiquidGlass from "liquid-glass-react";

/** Refraction stays behind content so labels, focus and hit targets remain stable. */
export function LiquidSurface({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`liquid-surface rl-glass ${className}`}>
      <div className="liquid-refraction" aria-hidden="true">
        <LiquidGlass
          mode="standard"
          displacementScale={28}
          blurAmount={0.15}
          saturation={115}
          aberrationIntensity={0.3}
          elasticity={0}
          cornerRadius={22}
          padding="0"
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            width: "100%",
            height: "100%",
          }}
        >
          <span />
        </LiquidGlass>
      </div>
      <div className="liquid-content">{children}</div>
    </div>
  );
}
