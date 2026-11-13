import type { CapturedFrame } from "./types"

export type EnrollmentAngleKey =
  | "front"
  | "slight_left"
  | "slight_right"
  | "left_profile"
  | "right_profile"

export interface EnrollmentAngleStep {
  angle: EnrollmentAngleKey
  stepNumber: number
  label: string
  shortLabel: string
  instruction: string
  direction: "center" | "left" | "right" | "far_left" | "far_right"
}

export const ENROLLMENT_ANGLE_STEPS: readonly EnrollmentAngleStep[] = [
  {
    angle: "front",
    stepNumber: 1,
    label: "Forward Facing",
    shortLabel: "Front",
    instruction: "Look straight ahead into the center oval",
    direction: "center",
  },
  {
    angle: "slight_left",
    stepNumber: 2,
    label: "Slight Left Turn",
    shortLabel: "Slight Left",
    instruction: "Turn your head slightly to the left (~15°)",
    direction: "left",
  },
  {
    angle: "slight_right",
    stepNumber: 3,
    label: "Slight Right Turn",
    shortLabel: "Slight Right",
    instruction: "Turn your head slightly to the right (~15°)",
    direction: "right",
  },
  {
    angle: "left_profile",
    stepNumber: 4,
    label: "Left Profile",
    shortLabel: "Left Profile",
    instruction: "Turn further left for a left profile view",
    direction: "far_left",
  },
  {
    angle: "right_profile",
    stepNumber: 5,
    label: "Right Profile",
    shortLabel: "Right Profile",
    instruction: "Turn further right for a right profile view",
    direction: "far_right",
  },
] as const

export const REQUIRED_ANGLE_COUNT = ENROLLMENT_ANGLE_STEPS.length

export function isValidCapturedFrame(frame?: CapturedFrame | null): boolean {
  return Boolean(
    frame &&
      frame.dataUrl &&
      frame.bbox &&
      frame.landmarks_5 &&
      (frame.status === "ready" || frame.status === "success" || frame.status === "enrolled"),
  )
}

export function getCollectedAngleCount(frames: CapturedFrame[]): number {
  const validAngles = new Set<string>()
  for (const frame of frames) {
    if (frame.angle && isValidCapturedFrame(frame)) {
      validAngles.add(frame.angle)
    }
  }
  return validAngles.size
}

export function getFrameForAngle(
  frames: CapturedFrame[],
  angle: EnrollmentAngleKey,
): CapturedFrame | undefined {
  return frames.find((f) => f.angle === angle)
}

export function getNextMissingAngle(
  frames: CapturedFrame[],
  afterAngle?: EnrollmentAngleKey,
): EnrollmentAngleKey {
  const startIdx = afterAngle
    ? ENROLLMENT_ANGLE_STEPS.findIndex((s) => s.angle === afterAngle)
    : -1

  for (let offset = 1; offset <= ENROLLMENT_ANGLE_STEPS.length; offset += 1) {
    const candidate =
      ENROLLMENT_ANGLE_STEPS[(Math.max(0, startIdx) + offset) % ENROLLMENT_ANGLE_STEPS.length]
    const existing = getFrameForAngle(frames, candidate.angle)
    if (!isValidCapturedFrame(existing)) {
      return candidate.angle
    }
  }
  return ENROLLMENT_ANGLE_STEPS[0].angle
}

export function areAllRequiredAnglesCollected(frames: CapturedFrame[]): boolean {
  return ENROLLMENT_ANGLE_STEPS.every((step) =>
    isValidCapturedFrame(getFrameForAngle(frames, step.angle)),
  )
}

