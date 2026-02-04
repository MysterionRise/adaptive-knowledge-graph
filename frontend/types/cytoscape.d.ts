import 'cytoscape';

declare module 'cytoscape' {
  interface CoseBilkentLayoutOptions {
    name: 'cose-bilkent';
    randomize?: boolean;
    nodeRepulsion?: number;
    idealEdgeLength?: number;
    edgeElasticity?: number;
    nestingFactor?: number;
    gravity?: number;
    numIter?: number;
    tile?: boolean;
    animate?: boolean | 'end' | 'during';
    animationDuration?: number;
    tilingPaddingVertical?: number;
    tilingPaddingHorizontal?: number;
    gravityRangeCompound?: number;
    gravityCompound?: number;
    gravityRange?: number;
    initialEnergyOnIncremental?: number;
    quality?: 'default' | 'draft' | 'proof';
  }

  interface LayoutOptions {
    name: string;
  }

  // Extend Stylesheet to allow function values for style properties
  interface StylesheetStyle {
    'background-color'?: string | ((ele: NodeSingular | EdgeSingular) => string);
    'width'?: number | string | ((ele: NodeSingular | EdgeSingular) => number | string);
    'height'?: number | string | ((ele: NodeSingular | EdgeSingular) => number | string);
    'line-color'?: string | ((ele: EdgeSingular) => string);
    'target-arrow-color'?: string | ((ele: EdgeSingular) => string);
    'transition-property'?: string;
    'transition-duration'?: number | string;
  }
}
