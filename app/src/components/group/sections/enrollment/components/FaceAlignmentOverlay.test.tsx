import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { FaceAlignmentOverlay } from "./FaceAlignmentOverlay"
import type { FaceAlignmentEvaluation } from "@/services/BackendService"

function makeAlignment(overrides: Partial<FaceAlignmentEvaluation> = {}): FaceAlignmentEvaluation {
  return {
    status: "ready",
    ready: true,
    guidance: "Aligned for Left Profile — hold steady or capture.",
    quality_issues: [],
    target_angle: "left_profile",
    angle_detected: "left_profile",
    metrics: {
      brightness: 132,
      sharpness: 88,
      quality_status: "green",
      quality_score: 0.91,
      clarity_score: 0.84,
      yaw: -24.5,
      pitch: 1.2,
      roll: -0.5,
      offset_x: 0.02,
      offset_y: -0.01,
      face_height_ratio: 0.56,
    },
    overlay: {
      image_width: 640,
      image_height: 480,
      mirrored: false,
      bbox: { x: 220, y: 110, width: 200, height: 260 },
      features: {
        left_eye: {
          center: { x: 270, y: 200 },
          contour: [
            { x: 255, y: 200 },
            { x: 270, y: 192 },
            { x: 285, y: 200 },
            { x: 270, y: 208 },
          ],
        },
        right_eye: {
          center: { x: 370, y: 200 },
          contour: [
            { x: 355, y: 200 },
            { x: 370, y: 192 },
            { x: 385, y: 200 },
            { x: 370, y: 208 },
          ],
        },
        left_eyebrow: [
          { x: 248, y: 176 },
          { x: 270, y: 168 },
          { x: 292, y: 174 },
        ],
        right_eyebrow: [
          { x: 348, y: 174 },
          { x: 370, y: 168 },
          { x: 392, y: 176 },
        ],
        nose: {
          tip: { x: 296, y: 245 },
          bridge: [
            { x: 320, y: 195 },
            { x: 308, y: 220 },
            { x: 296, y: 245 },
          ],
          base: [
            { x: 284, y: 250 },
            { x: 296, y: 245 },
            { x: 310, y: 250 },
          ],
        },
        mouth: {
          left: { x: 285, y: 295 },
          right: { x: 355, y: 295 },
          center: { x: 320, y: 295 },
          contour: [
            { x: 285, y: 295 },
            { x: 320, y: 285 },
            { x: 355, y: 295 },
            { x: 320, y: 306 },
          ],
        },
        left_ear: [
          { x: 215, y: 210 },
          { x: 205, y: 235 },
          { x: 215, y: 265 },
        ],
        right_ear: [
          { x: 425, y: 210 },
          { x: 435, y: 235 },
          { x: 425, y: 265 },
        ],
        face_outline: [
          { x: 320, y: 110 },
          { x: 420, y: 240 },
          { x: 320, y: 370 },
          { x: 220, y: 240 },
        ],
      },
      axes: {
        horizontal: { x1: 200, y1: 200, x2: 440, y2: 200, mid_x: 320, mid_y: 200 },
        vertical: { x1: 320, y1: 100, x2: 320, y2: 380, mid_x: 320, mid_y: 240 },
      },
      coordinates: {
        center_x: 320,
        center_y: 240,
        norm_x: 0.5,
        norm_y: 0.5,
        offset_x: 0.02,
        offset_y: -0.01,
        face_width_ratio: 0.31,
        face_height_ratio: 0.54,
        yaw: -24.5,
        pitch: 1.2,
        roll: -0.5,
        clarity_score: 0.84,
        brightness: 132,
        sharpness: 88,
        landmarks: {
          left_eye: { x: 270, y: 200 },
          right_eye: { x: 370, y: 200 },
          nose: { x: 296, y: 245 },
          left_mouth: { x: 285, y: 295 },
          right_mouth: { x: 355, y: 295 },
        },
      },
    },
    ...overrides,
  }
}

describe("FaceAlignmentOverlay", () => {
  it("renders facial feature guides, coordinate axes, telemetry HUD, and progress", () => {
    render(
      <FaceAlignmentOverlay
        alignment={makeAlignment()}
        currentAngle="left_profile"
        completedAngles={["front", "slight_left"]}
      />,
    )

    expect(screen.getByTestId("facial-landmark-svg")).toBeInTheDocument()
    expect(screen.getByTestId("guide-axis-horizontal")).toBeInTheDocument()
    expect(screen.getByTestId("guide-axis-vertical")).toBeInTheDocument()
    expect(screen.getByTestId("guide-face-outline")).toBeInTheDocument()
    expect(screen.getByTestId("guide-left-eye")).toBeInTheDocument()
    expect(screen.getByTestId("guide-right-eye")).toBeInTheDocument()
    expect(screen.getByTestId("guide-left-eyebrow")).toBeInTheDocument()
    expect(screen.getByTestId("guide-right-eyebrow")).toBeInTheDocument()
    expect(screen.getByTestId("guide-nose-bridge")).toBeInTheDocument()
    expect(screen.getByTestId("guide-nose-base")).toBeInTheDocument()
    expect(screen.getByTestId("guide-mouth")).toBeInTheDocument()
    expect(screen.getByTestId("guide-left-ear")).toBeInTheDocument()
    expect(screen.getByTestId("guide-right-ear")).toBeInTheDocument()

    expect(screen.getByText("2/5")).toBeInTheDocument()
    expect(screen.getByText("Left Profile")).toBeInTheDocument()
    expect(screen.getByTestId("alignment-coordinates-hud")).toHaveTextContent("X:320 Y:240")
    expect(screen.getByTestId("alignment-coordinates-hud")).toHaveTextContent("Yaw:-24.5°")
    expect(screen.getByTestId("alignment-guidance-banner")).toHaveTextContent(
      "Aligned for Left Profile",
    )
  })

  it("displays clear guidance when face is missing, off-center, poorly lit, or blurry", () => {
    const missing = makeAlignment({
      status: "missing",
      ready: false,
      guidance: "No face detected. Position your face inside the alignment oval.",
      overlay: null,
    })
    const { rerender } = render(
      <FaceAlignmentOverlay
        alignment={missing}
        currentAngle="front"
        completedAngles={[]}
      />,
    )
    expect(screen.getByTestId("alignment-guidance-banner")).toHaveTextContent("No face detected")
    expect(screen.getByTestId("alignment-coordinates-hud")).toHaveTextContent("Scanning face coords")

    rerender(
      <FaceAlignmentOverlay
        alignment={makeAlignment({
          status: "poor_lighting",
          ready: false,
          guidance: "Room is too dark. Increase front lighting on your face.",
        })}
        currentAngle="front"
        completedAngles={[]}
      />,
    )
    expect(screen.getByTestId("alignment-guidance-banner")).toHaveTextContent("Room is too dark")
  })
})

