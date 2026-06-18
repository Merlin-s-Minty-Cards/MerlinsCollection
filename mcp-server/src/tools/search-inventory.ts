export type SearchFilters = {
  name?: string;
  set?: string;
  condition?: string;
  minValue?: number;
  maxValue?: number;
};

export type CardResult = {
  id: string;
  name: string;
  set: string;
  condition: string;
  quantity: number;
  currentValue: number;
};

export async function searchInventory(filters: SearchFilters): Promise<CardResult[]> {
  throw new Error("Not implemented");
}
