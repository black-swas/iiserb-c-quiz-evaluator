#include <stdio.h>

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    // BUG: steps initialized to 1 instead of 0
    int steps = 1;
    while (n > 1) {
        if (n % 2 == 0) n /= 2;
        else n = 3 * n + 1;
        steps++;
    }
    printf("%d\n", steps);
    return 0;
}
