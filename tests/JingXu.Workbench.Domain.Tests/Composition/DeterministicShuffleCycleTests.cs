using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Tests.Composition;

public sealed class DeterministicShuffleCycleTests
{
    [Fact]
    public void Reshuffled_cycles_are_complete_different_reproducible_and_have_no_boundary_repeat()
    {
        const int itemCount = 5;
        var sequence = Enumerable.Range(0, itemCount * 3)
            .Select(i => DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                itemCount,
                seed: 264513,
                selectionOrdinal: i,
                branchIndex: 1))
            .ToArray();

        var cycles = sequence.Chunk(itemCount).Select(chunk => chunk.ToArray()).ToArray();
        Assert.All(cycles, cycle => Assert.Equal(
            Enumerable.Range(0, itemCount),
            cycle.OrderBy(index => index)));
        Assert.False(cycles[0].SequenceEqual(cycles[1]));
        Assert.False(cycles[1].SequenceEqual(cycles[2]));
        Assert.All(sequence.Zip(sequence.Skip(1)), pair => Assert.NotEqual(pair.First, pair.Second));

        var replay = Enumerable.Range(0, sequence.Length)
            .Select(i => DeterministicShuffleCycle.SelectIndexWithReshuffledCycles(
                itemCount,
                seed: 264513,
                selectionOrdinal: i,
                branchIndex: 1))
            .ToArray();
        Assert.Equal(sequence, replay);
    }

    [Fact]
    public void Legacy_selector_keeps_its_existing_repeating_cycle_for_mask_callers()
    {
        const int itemCount = 5;
        var first = Enumerable.Range(0, itemCount)
            .Select(i => DeterministicShuffleCycle.SelectIndex(itemCount, 264513, i, 0))
            .ToArray();
        var second = Enumerable.Range(itemCount, itemCount)
            .Select(i => DeterministicShuffleCycle.SelectIndex(itemCount, 264513, i, 0))
            .ToArray();

        Assert.Equal(first, second);
    }
}
