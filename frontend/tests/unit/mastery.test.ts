import {
  MASTERY_BAND_LABELS,
  MASTERY_BAND_STYLES,
  MASTERY_IN_PROGRESS,
  MASTERY_MASTERED,
  masteryBand,
  type MasteryBand,
} from '@/lib/mastery';

const BANDS: MasteryBand[] = ['mastered', 'in_progress', 'to_learn'];

describe('masteryBand', () => {
  it.each<[number, MasteryBand]>([
    [0, 'to_learn'],
    [0.39, 'to_learn'],
    [0.4, 'in_progress'],
    [0.69, 'in_progress'],
    [0.7, 'mastered'],
    [1, 'mastered'],
  ])('classifies a mastery of %s as %s', (mastery, band) => {
    expect(masteryBand(mastery)).toBe(band);
  });

  it('starts each band at the exported threshold', () => {
    expect(MASTERY_IN_PROGRESS).toBeLessThan(MASTERY_MASTERED);
    expect(masteryBand(MASTERY_IN_PROGRESS)).toBe('in_progress');
    expect(masteryBand(MASTERY_MASTERED)).toBe('mastered');
  });
});

describe('mastery band labels and styles', () => {
  it('labels every band', () => {
    expect(MASTERY_BAND_LABELS).toEqual({
      mastered: 'Mastered',
      in_progress: 'In Progress',
      to_learn: 'To Learn',
    });
  });

  it('colours mastered green, in progress blue and to learn gray', () => {
    expect(MASTERY_BAND_STYLES.mastered.bar).toBe('bg-emerald-500');
    expect(MASTERY_BAND_STYLES.in_progress.bar).toBe('bg-blue-500');
    expect(MASTERY_BAND_STYLES.to_learn.bar).toBe('bg-gray-300');
  });

  it.each(BANDS)('gives the %s band a bar, text, chip and stroke class', (band) => {
    const styles = MASTERY_BAND_STYLES[band];

    expect(styles.bar).toMatch(/^bg-[a-z]+-\d{3}$/);
    expect(styles.text).toMatch(/^text-[a-z]+-\d{3}$/);
    expect(styles.stroke).toMatch(/^stroke-[a-z]+-\d{3}$/);
    expect(styles.chip.split(' ')).toEqual([
      expect.stringMatching(/^text-/),
      expect.stringMatching(/^bg-/),
      expect.stringMatching(/^border-/),
    ]);
  });
});
