import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Writing — Metalins Research Lab";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#09090b",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
        }}
      >
        <div
          style={{
            color: "#71717a",
            fontSize: 18,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            marginBottom: 24,
            fontFamily: "monospace",
          }}
        >
          metalins.com / writing
        </div>
        <div
          style={{
            color: "#fafafa",
            fontSize: 64,
            fontWeight: 700,
            lineHeight: 1.1,
            marginBottom: 24,
          }}
        >
          Writing
        </div>
        <div
          style={{
            color: "#a1a1aa",
            fontSize: 28,
            lineHeight: 1.4,
            maxWidth: 800,
          }}
        >
          Papers, essays, and research from the Metalins lab.
        </div>
      </div>
    ),
    size
  );
}
