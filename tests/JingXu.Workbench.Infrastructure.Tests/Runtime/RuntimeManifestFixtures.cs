namespace JingXu.Workbench.Infrastructure.Tests.Runtime;

internal static class RuntimeManifestFixtures
{
    public static string Read(string fileName)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Runtime", "Fixtures", fileName);
        return File.ReadAllText(path);
    }
}
