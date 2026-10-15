#include <stdio.h>

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    int steps = 0;
    // BUG: forgets to divide n, leading to infinite loop
    while (n > 1) {
        steps++;
    }
    printf("%d\n", steps);
    return 0;
}
