export type InventoryValueResult = {
  totalValue: number;
  valueBySet: Record<string, number>;
  valueByCondition: Record<string, number>;
  calculatedAt: string;
};

export async function calculateInventoryValue(): Promise<InventoryValueResult> {
  throw new Error("Not implemented");
}
