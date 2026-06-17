import type { SVGProps } from "react";

/**
 * 松鼠品牌图标组件
 * @param size - 图标尺寸（px），默认 40
 */
export default function SquirrelLogo({ size = 40, className, ...props }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={className}
      {...props}
    >
      <defs>
        <linearGradient id="squirrel-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#F97316" />
          <stop offset="100%" stopColor="#EA580C" />
        </linearGradient>
      </defs>
      {/* 背景圆角方块 */}
      <rect x="4" y="4" width="56" height="56" rx="14" fill="url(#squirrel-bg)" />
      {/* 松鼠头 */}
      <ellipse cx="32" cy="34" rx="14" ry="13" fill="#FEF3C7" />
      {/* 左耳 */}
      <ellipse cx="21" cy="20" rx="5" ry="7" fill="#FEF3C7" transform="rotate(-15 21 20)" />
      <ellipse cx="21.5" cy="20.5" rx="3" ry="5" fill="#F97316" transform="rotate(-15 21.5 20.5)" opacity="0.3" />
      {/* 右耳 */}
      <ellipse cx="43" cy="20" rx="5" ry="7" fill="#FEF3C7" transform="rotate(15 43 20)" />
      <ellipse cx="42.5" cy="20.5" rx="3" ry="5" fill="#F97316" transform="rotate(15 42.5 20.5)" opacity="0.3" />
      {/* 左眼 */}
      <circle cx="26" cy="31" r="2.5" fill="#1C1917" />
      <circle cx="26.8" cy="30.2" r="0.8" fill="#fff" />
      {/* 右眼 */}
      <circle cx="38" cy="31" r="2.5" fill="#1C1917" />
      <circle cx="38.8" cy="30.2" r="0.8" fill="#fff" />
      {/* 鼻子 */}
      <ellipse cx="32" cy="37" rx="2" ry="1.5" fill="#1C1917" />
      {/* 嘴巴 */}
      <path d="M30 39 Q32 41 34 39" stroke="#1C1917" strokeWidth="1" fill="none" strokeLinecap="round" />
      {/* 腮红 */}
      <circle cx="22" cy="36" r="3" fill="#FB923C" opacity="0.35" />
      <circle cx="42" cy="36" r="3" fill="#FB923C" opacity="0.35" />
      {/* 松鼠尾巴（右侧卷曲） */}
      <path d="M46 38 Q54 28 50 18 Q47 12 42 14" stroke="#FEF3C7" strokeWidth="5" fill="none" strokeLinecap="round" />
    </svg>
  );
}
