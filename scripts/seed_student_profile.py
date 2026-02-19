"""
Seed a realistic demo student profile.

Creates a student profile with mixed mastery levels across
US History and Economics topics, enabling immediate demonstration
of adaptive features without needing to complete 10+ quizzes.

Usage:
    poetry run python scripts/seed_student_profile.py
    poetry run python scripts/seed_student_profile.py --student-id demo_user
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path


def create_demo_profile(student_id: str = "default") -> dict:
    """Create a realistic student profile with mixed mastery levels."""
    now = datetime.now()

    # US History topics — mix of mastered, in-progress, and weak areas
    us_history_concepts = {
        # Strong areas (80%+ mastery) — student has studied these well
        "The American Revolution": {
            "concept_name": "The American Revolution",
            "mastery_level": 0.85,
            "attempts": 12,
            "correct_attempts": 10,
            "last_assessed": (now - timedelta(hours=2)).isoformat(),
        },
        "The Constitution": {
            "concept_name": "The Constitution",
            "mastery_level": 0.78,
            "attempts": 9,
            "correct_attempts": 7,
            "last_assessed": (now - timedelta(hours=3)).isoformat(),
        },
        "Colonial America": {
            "concept_name": "Colonial America",
            "mastery_level": 0.92,
            "attempts": 15,
            "correct_attempts": 14,
            "last_assessed": (now - timedelta(days=1)).isoformat(),
        },
        # Medium areas (40-70% mastery) — actively learning
        "The Civil War": {
            "concept_name": "The Civil War",
            "mastery_level": 0.55,
            "attempts": 6,
            "correct_attempts": 3,
            "last_assessed": (now - timedelta(hours=1)).isoformat(),
        },
        "Industrialization": {
            "concept_name": "Industrialization",
            "mastery_level": 0.48,
            "attempts": 5,
            "correct_attempts": 2,
            "last_assessed": (now - timedelta(hours=4)).isoformat(),
        },
        "Westward Expansion": {
            "concept_name": "Westward Expansion",
            "mastery_level": 0.63,
            "attempts": 8,
            "correct_attempts": 5,
            "last_assessed": (now - timedelta(days=1)).isoformat(),
        },
        # Weak areas (20-40% mastery) — needs remediation
        "World War II": {
            "concept_name": "World War II",
            "mastery_level": 0.30,
            "attempts": 3,
            "correct_attempts": 1,
            "last_assessed": (now - timedelta(hours=5)).isoformat(),
        },
        "The Great Depression": {
            "concept_name": "The Great Depression",
            "mastery_level": 0.25,
            "attempts": 4,
            "correct_attempts": 1,
            "last_assessed": (now - timedelta(days=2)).isoformat(),
        },
        "Civil Rights Movement": {
            "concept_name": "Civil Rights Movement",
            "mastery_level": 0.35,
            "attempts": 3,
            "correct_attempts": 1,
            "last_assessed": (now - timedelta(days=1)).isoformat(),
        },
    }

    # Economics topics — fewer entries, earlier stage of learning
    economics_concepts = {
        "Supply and Demand": {
            "concept_name": "Supply and Demand",
            "mastery_level": 0.72,
            "attempts": 8,
            "correct_attempts": 6,
            "last_assessed": (now - timedelta(hours=6)).isoformat(),
        },
        "Market Equilibrium": {
            "concept_name": "Market Equilibrium",
            "mastery_level": 0.45,
            "attempts": 4,
            "correct_attempts": 2,
            "last_assessed": (now - timedelta(hours=8)).isoformat(),
        },
        "Fiscal Policy": {
            "concept_name": "Fiscal Policy",
            "mastery_level": 0.20,
            "attempts": 2,
            "correct_attempts": 0,
            "last_assessed": (now - timedelta(days=3)).isoformat(),
        },
    }

    # Combine all concepts
    all_concepts = {**us_history_concepts, **economics_concepts}

    # Calculate overall ability
    mastery_values = [
        c["mastery_level"] for c in all_concepts.values() if isinstance(c["mastery_level"], float)
    ]
    overall_ability = sum(mastery_values) / len(mastery_values)

    profile = {
        student_id: {
            "student_id": student_id,
            "mastery_map": all_concepts,
            "overall_ability": round(overall_ability, 3),
            "created_at": (now - timedelta(days=7)).isoformat(),
            "updated_at": now.isoformat(),
        }
    }

    return profile


def main():
    parser = argparse.ArgumentParser(description="Seed demo student profile")
    parser.add_argument(
        "--student-id",
        default="default",
        help="Student ID to create (default: 'default')",
    )
    parser.add_argument(
        "--output",
        default="data/processed/student_profiles.json",
        help="Output path for student profiles JSON",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing profiles if any
    existing = {}
    if output_path.exists():
        with open(output_path) as f:
            existing = json.load(f)

    # Create demo profile
    demo_profile = create_demo_profile(args.student_id)

    # Merge — demo profile overwrites existing for the same student_id
    existing.update(demo_profile)

    with open(output_path, "w") as f:
        json.dump(existing, f, indent=2, default=str)

    print(f"Demo student profile seeded at {output_path}")
    print(f"  Student ID: {args.student_id}")
    print(f"  Concepts tracked: {len(demo_profile[args.student_id]['mastery_map'])}")
    print(f"  Overall ability: {demo_profile[args.student_id]['overall_ability']:.0%}")

    # Print summary table
    print("\n  Mastery Summary:")
    print(f"  {'Concept':<30} {'Mastery':>8} {'Level':>8}")
    print(f"  {'─' * 48}")
    for name, data in demo_profile[args.student_id]["mastery_map"].items():
        mastery = data["mastery_level"]
        level = "easy" if mastery < 0.4 else "medium" if mastery <= 0.7 else "hard"
        bar = "█" * int(mastery * 10) + "░" * (10 - int(mastery * 10))
        print(f"  {name:<30} {bar} {mastery:>5.0%}  {level}")


if __name__ == "__main__":
    main()
