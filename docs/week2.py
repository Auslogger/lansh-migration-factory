from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.dummy import DummyClassifier


def plot_targets(ax, X, y):
    """
    Plot the known +1 and -1 labels at their original feature coordinates.

    X has one row per observation and columns for x1 and x2. The binary masks made
    from y select the rows belonging to each target class.

    Args:
        ax: Matplotlib axes on which to draw the markers.
        X: Two col feature matrix, with one row per observation.
        y: Actual +1 or -1 label for each row of X.
    """
    ax.scatter(
        X[y == 1, 0], X[y == 1, 1],
        marker="P", color="yellow", edgecolors="black", linewidths=0.4, label="Target +1"
    )
    ax.scatter(
        X[y == -1, 0], X[y == -1, 1],
        marker="o", color="purple", edgecolors="black", label="Target -1"
    )

def plot_predictions(ax, X, predictions):
    """
    Overlay predicted class markers at the corresponding rows of X.

    predictions is a 1D array aligned with X. Its ith value is
    the predicted label for the ith feature pair, not a new plot coordinate.

    Args:
        ax: Matplotlib axes on which to draw the markers.
        X: Original two col feature matrix used for plot coordinates.
        predictions: Predicted +1 or -1 label for each row of X.
    """
    ax.scatter(
        X[predictions == 1, 0], X[predictions == 1, 1],
        marker="+", color="red", s=80, linewidths=0.5, label="Predicted +1"
    )
    ax.scatter(
        X[predictions == -1, 0], X[predictions == -1, 1],
        marker="o", facecolors="none", edgecolors="green", s=80, linewidths=1, label="Predicted -1"
    )

def plot_linear_boundary(ax, model):
    """
    Draw the decision boundary line of a fitted 2 feature linear classifier.

    Rearranging b + w1*x1 + w2*x2 = 0 gives a vertical axis intercept
    of -b/w2 and a slope of -w1/w2 (given w2 = nonzero).

    Args:
        ax: Matplotlib axes on which to draw the line.
        model: Fitted two-feature classifier with intercept_ and coef_
    """
    b = model.intercept_[0]
    w1, w2 = model.coef_[0]

    ax.axline(
        (0, -b/w2),
        slope=-w1/w2,
        color="blue", linewidth=2, label="Decision boundary"
    )

def print_model_info(name, model, feature_names, predictions, y):
    """
    Print fitted parameters and accuracy on the given target labels.

    feature_names must match the order of the model's input columns. 
    Each prediction is compared with the target for the same observation.
    This func reports training accuracy when the inputs were also used to fit the model.

    Args:
        name: Heading used to identify the model in console output.
        model: Fitted classifier with intercept_ and coef_
        feature_names: Labels in the same order as the model's input columns.
        predictions: Predicted label for each observation.
        y: Actual label for each observation aligned with predictions.
    """
    b = model.intercept_[0]
    weights = model.coef_[0]

    # count matching labels then divide by the num of observations
    correct = np.sum(predictions == y)
    incorrect = len(y) - correct
    accuracy = (correct/len(y)) * 100

    print(name)
    print(f"Intercept/bias: {b:.4f}")

    for feature_name, weight in zip(feature_names, weights):
        print(f"{feature_name} weight/parameter: {weight:.4f}")

    print(f"Correct predictions: {correct}")
    print(f"Incorrect predictions: {incorrect}")
    print(f"Training accuracy: {accuracy:.2f}%\n")

# ensure dataset is found on any machine
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = PROJECT_ROOT / "dataset" / "week2.csv"

print("------------------------") # formatting
# print ID line
with DATA_PATH.open() as file:
    print(file.readline().rstrip(), "\n")

# exclude the first ID line row without discarding the first actual observation
df = pd.read_csv(DATA_PATH, skiprows=1, header=None)

X1 = df.iloc[:, 0] # first measured feature
X2 = df.iloc[:, 1] # second measured feature
X = np.column_stack((X1, X2)) # two column feature matrix
y = df.iloc[:, 2] # actual class labels

### a) i)

fig, ax1 = plt.subplots(layout="constrained")

plot_targets(ax1, X, y)
ax1.set(
    xlabel="$x_1$",
    ylabel="$x_2$",
    title="a) i): Feature values against their targets"
)
ax1.legend(loc="upper left", bbox_to_anchor=(1, 1))
plt.savefig("plots/features.png", dpi=300, bbox_inches="tight")

### a) ii)

# disable regularisation so the fitted logistic model uses logistic loss only
LR_model = LogisticRegression(penalty=None, solver="lbfgs")
LR_model.fit(X, y) # learn the intercept and weights from training data

### a) iii)

# predict labels for same rows used in fitting (training set)
# a +1 probability above 0.5 predicts +1
LR_y_pred = LR_model.predict(X)

# plot targets and predictions at same coordinates to expose mismatches
fig, ax2 = plt.subplots(layout="constrained")

print_model_info("Logistic Regression", LR_model, ["x_1", "x_2"], LR_y_pred, y)
plot_targets(ax2, X, y)
plot_predictions(ax2, X, LR_y_pred)
plot_linear_boundary(ax2, LR_model)

ax2.set(
    xlabel="$x_1$",
    ylabel="$x_2$",
    title="a) (iii) Logistic Regression: Training Labels, Predictions and Decision Boundary"
)
ax2.legend(loc="upper left", bbox_to_anchor=(1, 1))
plt.savefig("plots/LR_pred_db.png", dpi=300, bbox_inches="tight")

### b) i)

# smaller C gives stronger regularisation ; larger C penalises violations more
SVM_0001 = LinearSVC(C=0.001).fit(X, y)
SVM_1 = LinearSVC(C=1).fit(X, y)
SVM_100 = LinearSVC(C=100).fit(X, y)

### b) ii)

# compare all 3 classifiers on the same training observations
SVM0001_y_pred = SVM_0001.predict(X)
SVM1_y_pred = SVM_1.predict(X)
SVM100_y_pred = SVM_100.predict(X)

fig, (ax3, ax4, ax5) = plt.subplots(
    1, 3,
    figsize=(16, 5), sharex=True, sharey=True, layout="constrained"
)

# shared axis to make the 3 decision boundaries directly comparable
print_model_info("SVM C=0.001", SVM_0001, ["x_1", "x_2"], SVM0001_y_pred, y)
plot_targets(ax3, X, y)
plot_predictions(ax3, X, SVM0001_y_pred)
plot_linear_boundary(ax3, SVM_0001)
ax3.set_title("b) ii): Linear SVM: C = 0.001")

print_model_info("SVM C=1", SVM_1, ["x_1", "x_2"], SVM1_y_pred, y)
plot_targets(ax4, X, y)
plot_predictions(ax4, X, SVM1_y_pred)
plot_linear_boundary(ax4, SVM_1)
ax4.set_title("Linear SVM: C = 1")

print_model_info("SVM C=100", SVM_100, ["x_1", "x_2"], SVM100_y_pred, y)
plot_targets(ax5, X, y)
plot_predictions(ax5, X, SVM100_y_pred)
plot_linear_boundary(ax5, SVM_100)
ax5.set_title("Linear SVM: C = 100")

fig.supxlabel("$x_1$")
fig.supylabel("$x_2$")
ax5.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
plt.savefig("plots/3svm.png", dpi=300, bbox_inches="tight")

### c) i)

# append x1^2 and x2^2 as columns 3 and 4.
X_engineered = np.column_stack((X1, X2, X1**2, X2**2))

LR_model_engineered = LogisticRegression(penalty=None, solver="lbfgs")
LR_model_engineered.fit(X_engineered, y)

### c) ii)

# predict with four features
LR_engineered_y_pred = LR_model_engineered.predict(X_engineered)

print_model_info("Feature Engineered Logistic Regression", LR_model_engineered, 
                 ["x_1", "x_2", "x^2_1", "x^2_2"], LR_engineered_y_pred, y)

fig, ax6 = plt.subplots(layout="constrained")

plot_targets(ax6, X, y)
plot_predictions(ax6, X, LR_engineered_y_pred)

ax6.set(
    xlabel="$x_1$",
    ylabel="$x_2$",
    title="c): Feature engineered logistic regression"
)

### c) iii)

# baseline learns only the most frequent label and ignores feature values.
baseline_model = DummyClassifier(strategy="most_frequent")
baseline_model.fit(X_engineered, y)

# predicting on the same rows to make accuracy comparable to new model
baseline_predictions = baseline_model.predict(X_engineered)

baseline_correct = np.sum(baseline_predictions == y)
baseline_incorrect = len(y) - baseline_correct
baseline_accuracy = (baseline_correct/len(y)) * 100
print("Baseline - most frequent")
print(f"Correct predictions: {baseline_correct}")
print(f"Incorrect predictions: {baseline_incorrect}")
print(f"Training accuracy: {baseline_accuracy:.2f}%")

### c) iv)

# at each x1 solve the zero-score equation as a quadratic in x2
boundary_x1 = np.linspace(-1, 1, 401)
b = LR_model_engineered.intercept_[0]
w1, w2, w3, w4 = LR_model_engineered.coef_[0]

# here C is the quadratics constant term, not the SVM penalty parameter
C = b + w1 * boundary_x1 + w3 * boundary_x1**2
# the plus sign root results only are the ones visible within the plot's feature range
boundary_x2 = (-w2 + np.sqrt(w2**2 - 4 * w4 * C)) / (2 * w4)

ax6.plot(boundary_x1, boundary_x2, color="blue", linewidth=2, label="Decision boundary")

ax6.legend(loc="upper left", bbox_to_anchor=(1, 1))
plt.savefig("plots/FE_LR.png", dpi=300, bbox_inches="tight")

plt.show()
