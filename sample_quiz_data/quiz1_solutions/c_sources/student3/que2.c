#include <stdio.h>

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    int s = 0;
    while (n > 1) {
        n = (n % 2 == 0) ? (n / 2) : (3 * n + 1);
        s++;
    }
    printf("%d\n", s);
    return 0;
}
