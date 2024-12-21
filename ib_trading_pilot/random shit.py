
from scipy.stats import chi2

# Degrees of freedom
df = 5543

# Critical values for 95% confidence interval
chi2_lower = chi2.ppf(0.025, df)
chi2_upper = chi2.ppf(0.975, df)

print("Chi-squared lower (0.025):", chi2_lower)
print("Chi-squared upper (0.975):", chi2_upper)
x=2